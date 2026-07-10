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

import re
import time

MAX_REINTENTOS = 4
ESPERA_MIN_SEGUNDOS = 5
ESPERA_MAXIMA_SEGUNDOS = 60


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
                           max_reintentos: int = MAX_REINTENTOS):
    """
    Ejecuta funcion_llamada() (sin argumentos, típicamente un lambda que hace
    la llamada real a cliente.models.generate_content(...)) y, si falla con
    un error transitorio (429/503), espera el tiempo sugerido por la propia
    API (o un backoff exponencial si no lo indica) y reintenta.

    Lanza la excepción original si se agotan los reintentos o si el error
    no es transitorio, para que el llamador decida cómo manejarlo.
    """
    ultimo_error = None

    for intento in range(1, max_reintentos + 1):
        try:
            return funcion_llamada()
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
                espera += 1  # margen de seguridad sobre lo que pide la API

            print(f"  [~] '{etiqueta}': error transitorio (intento {intento}/{max_reintentos}). "
                  f"Esperando {espera:.0f}s antes de reintentar...")
            time.sleep(espera)

    raise ultimo_error
