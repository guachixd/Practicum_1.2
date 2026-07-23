"""
reintentos.py — Reintentos con espera para llamadas a la API de Gemini

Utilidad compartida por generador_recursos.py y evaluador.py.
La capa gratuita de Gemini responde con error 429 (RESOURCE_EXHAUSTED) cuando
se agota la cuota por minuto o por día, y normalmente incluye en el propio
mensaje de error un campo "retryDelay" (ej. "35s") indicando cuánto esperar.
Este módulo lee ese valor y pausa la ejecución en vez de reintentar de
inmediato — reintentar sin esperar solo consume más cuota y empeora el error
en cascada (esto es justo lo que le pasó al pipeline: cada reintento fallido
dispara otra llamada contra una cuota que ya está en cero).

También cubre el caso 503 (UNAVAILABLE, "modelo con alta demanda"), donde
Gemini no da retryDelay: ahí se usa un backoff exponencial simple.
"""

import os
import re
import time

MAX_REINTENTOS = 4
ESPERA_MIN_SEGUNDOS = 5
ESPERA_MAXIMA_SEGUNDOS = 60

# Espera deliberada DESPUÉS de cada llamada exitosa a Gemini, para consumir
# la cuota de forma pausada/iterativa en vez de en ráfaga. Antes había un
# solo número (4s) para todos los modelos, pero cada modelo tiene su PROPIO
# límite de solicitudes por minuto (RPM) en el nivel gratuito, y no son
# iguales: viendo el panel de uso real de una cuenta, gemini-2.5-flash
# permite apenas 5 solicitudes por minuto, mientras que gemini-2.5-flash-lite
# permite 10. Un espaciado de 4s (unas 15 llamadas por minuto) es más rápido
# que el límite real de ambos modelos, así que igual se agotaba la cuota por
# minuto aunque hubiera espera. Ahora cada modelo espera lo que le
# corresponde según su propio límite (con un colchón de seguridad, no el
# número justo). "otro" es el valor por defecto para cualquier modelo que
# no esté en esta lista.
SEGUNDOS_ENTRE_LLAMADAS_POR_MODELO = {
    "gemini-2.5-flash": 13,       # límite real: 5 solicitudes/minuto -> 60/5 = 12s, con colchón
    "gemini-2.5-flash-lite": 7,   # límite real: 10 solicitudes/minuto -> 60/10 = 6s, con colchón
    "otro": float(os.getenv("SEGUNDOS_ENTRE_LLAMADAS_IA", "13")),
}


class CuotaAgotadaError(Exception):
    """
    Se agotaron los reintentos ante un error transitorio de la API de Gemini
    (cuota/tokens agotados por minuto o por día, o modelo saturado).

    A diferencia de una excepción genérica, esta señal específica le permite
    al pipeline (pipeline.py) detener la ejecución de forma ORDENADA en vez
    de reventar el proceso: guarda en la base de datos exactamente en qué
    unidad/recurso se quedó, marca el trabajo como 'pausado_sin_creditos' y
    le informa al docente en la pantalla que puede continuar la generación
    más tarde desde donde se quedó, sin perder lo que ya se generó.
    """
    pass


def _segundos_sugeridos_por_la_api(excepcion: Exception) -> float | None:
    """
    Busca un campo tipo "retryDelay': '35s'" o "retry_delay { seconds: 35 }"
    en el texto de la excepción y devuelve los segundos como float.
    Devuelve None si no se encuentra ninguna pista.
    """
    texto = str(excepcion)

    coincidencia = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)\s*s", texto)
    if coincidencia:
        return float(coincidencia.group(1))

    coincidencia = re.search(r"seconds:\s*(\d+)", texto)
    if coincidencia:
        return float(coincidencia.group(1))

    return None


def _es_error_reintentable(excepcion: Exception) -> bool:
    """
    429 (cuota agotada) y 503 (modelo sobrecargado) son transitorios y vale
    la pena esperar y reintentar. Cualquier otro error (401, 400, etc.) es
    un problema real de configuración o del prompt, no de disponibilidad,
    así que ahí no tiene sentido reintentar.
    """
    texto = str(excepcion)
    return "429" in texto or "RESOURCE_EXHAUSTED" in texto or "503" in texto or "UNAVAILABLE" in texto


def llamar_con_reintentos(funcion_llamada, etiqueta: str,
                           max_reintentos: int = MAX_REINTENTOS,
                           modelo: str = "otro"):
    """
    Ejecuta funcion_llamada() (sin argumentos, típicamente un lambda que hace
    la llamada real a cliente.models.generate_content(...)) y, si falla con
    un error transitorio (429/503), espera el tiempo sugerido por la propia
    API (o un backoff exponencial si no lo indica) y reintenta.

    `modelo` se usa solo para saber cuánto esperar DESPUÉS de una llamada
    exitosa (cada modelo tiene su propio límite de solicitudes por minuto).

    Lanza CuotaAgotadaError si se agotan los reintentos de un error
    transitorio (cuota/tokens agotados), o vuelve a lanzar la excepción
    original tal cual si el error no es transitorio, para que el llamador
    decida cómo manejarlo.
    """
    ultimo_error = None
    espera_entre_llamadas = SEGUNDOS_ENTRE_LLAMADAS_POR_MODELO.get(
        modelo, SEGUNDOS_ENTRE_LLAMADAS_POR_MODELO["otro"]
    )

    for intento in range(1, max_reintentos + 1):
        try:
            resultado = funcion_llamada()
            if espera_entre_llamadas > 0:
                time.sleep(espera_entre_llamadas)
            return resultado
        except Exception as e:
            ultimo_error = e

            if not _es_error_reintentable(e):
                raise

            if intento == max_reintentos:
                break

            espera = _segundos_sugeridos_por_la_api(e)
            if espera is None:
                espera = min(ESPERA_MIN_SEGUNDOS * (2 ** (intento - 1)), ESPERA_MAXIMA_SEGUNDOS)
            else:
                # Si la API sugiere un tiempo de espera (ej. porque la cuota
                # DIARIA está agotada y falta mucho para que se reinicie),
                # NUNCA hay que dormir ese tiempo completo: podrían ser
                # minutos u horas, y el hilo se quedaría "colgado" en
                # silencio sin que el docente vea ningún avance ni error.
                # Se limita al mismo tope que el backoff normal; si la
                # cuota diaria de verdad está en cero, es mejor agotar los
                # reintentos rápido y pausar el trabajo (para que se
                # retome más tarde con "Continuar procesando") que bloquear
                # el proceso esperando a ciegas.
                espera = min(espera + 1, ESPERA_MAXIMA_SEGUNDOS)

            print(f"  [~] '{etiqueta}': error transitorio (intento {intento}/{max_reintentos}). "
                  f"Esperando {espera:.0f}s antes de reintentar...")
            time.sleep(espera)

    print(f"  [X] '{etiqueta}': se agotaron los reintentos. Probablemente se acabó la cuota/tokens "
          f"disponibles de la API de Gemini por ahora.")
    raise CuotaAgotadaError(str(ultimo_error))
