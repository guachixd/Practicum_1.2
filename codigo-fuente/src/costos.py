"""
costos.py — Seguimiento de costos aproximados de la ejecución

Cada respuesta de la API de Gemini trae un campo `usage_metadata` con el
conteo REAL de tokens de esa llamada (prompt_token_count,
candidates_token_count) — no es una estimación por caracteres, es lo que
Google efectivamente factura. Este módulo junta ese dato en cada llamada
(generador_recursos.py, clasificador.py, evaluador.py) y arma una tablita
de costos aproximados que se imprime en consola al terminar cada
ejecución (o al pausarse por falta de cuota).

Aislado por ejecución con contextvars: cada corrida del pipeline (un hilo
por trabajo en la web, o el proceso principal en la consola) tiene su
propio registro, así que no se mezclan los conteos de trabajos distintos
que corran en paralelo.

Los precios son los oficiales de https://ai.google.dev/gemini-api/docs/pricing
(consultados julio 2026), en USD por 1,000,000 de tokens. Si en el futuro
se usa un modelo que no está en este diccionario, la tabla lo señala en
vez de inventar un precio.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field

PRECIOS_USD_POR_MILLON = {
    # modelo: (precio_entrada, precio_salida)
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.00),
}


@dataclass
class _Registro:
    llamadas: list = field(default_factory=list)  # (modelo, etiqueta, tokens_in, tokens_out)


_registro_actual: contextvars.ContextVar[_Registro | None] = contextvars.ContextVar(
    "registro_actual", default=None
)


def iniciar_registro() -> None:
    """Arranca un registro limpio para esta ejecución (llamar al inicio del pipeline)."""
    _registro_actual.set(_Registro())


def _registro() -> _Registro:
    r = _registro_actual.get()
    if r is None:
        # Nadie llamó iniciar_registro() explícitamente (ej. un script suelto
        # de prueba): se crea uno igual para no romper la llamada.
        r = _Registro()
        _registro_actual.set(r)
    return r


def registrar_uso(modelo: str, etiqueta: str, respuesta) -> None:
    """
    Extrae los tokens reales reportados por la API en `respuesta.usage_metadata`
    y los suma al registro de esta ejecución. Si la respuesta no trae ese
    dato (SDK distinto, mock de pruebas, etc.), se registra la llamada con
    0 tokens en vez de inventar un número.
    """
    tokens_in = 0
    tokens_out = 0
    meta = getattr(respuesta, "usage_metadata", None)
    if meta is not None:
        tokens_in = getattr(meta, "prompt_token_count", None) or 0
        tokens_out = getattr(meta, "candidates_token_count", None) or 0

    _registro().llamadas.append((modelo, etiqueta, tokens_in, tokens_out))


def resumen_texto(titulo: str = "Costos aproximados de esta ejecución") -> str:
    """
    Arma la tablita de costos en texto plano, lista para imprimir en la
    consola (de PyCharm, de una terminal, o de un servidor Flask).
    """
    llamadas = _registro().llamadas
    if not llamadas:
        return ""

    por_modelo: dict[str, dict[str, float | int]] = {}
    for modelo, _etiqueta, tin, tout in llamadas:
        acumulado = por_modelo.setdefault(modelo, {"llamadas": 0, "in": 0, "out": 0})
        acumulado["llamadas"] += 1
        acumulado["in"] += tin
        acumulado["out"] += tout

    filas = []
    total_llamadas = total_in = total_out = 0
    costo_total = 0.0
    algun_modelo_sin_precio = False

    for modelo, datos in por_modelo.items():
        total_llamadas += datos["llamadas"]
        total_in += datos["in"]
        total_out += datos["out"]

        precios = PRECIOS_USD_POR_MILLON.get(modelo)
        if precios is None:
            costo_texto = "—"
            algun_modelo_sin_precio = True
        else:
            precio_in, precio_out = precios
            costo = (datos["in"] / 1_000_000) * precio_in + (datos["out"] / 1_000_000) * precio_out
            costo_total += costo
            costo_texto = f"${costo:.4f}"

        filas.append((modelo, datos["llamadas"], datos["in"], datos["out"], costo_texto))

    ancho_modelo = max([len("Modelo")] + [len(f[0]) for f in filas]) + 2
    linea = "=" * 78

    salida = [linea, f" {titulo}", linea]
    encabezado = (
        f" {'Modelo'.ljust(ancho_modelo)}{'Llamadas'.rjust(10)}"
        f"{'Tokens entrada'.rjust(16)}{'Tokens salida'.rjust(15)}{'Costo aprox.'.rjust(14)}"
    )
    salida.append(encabezado)
    salida.append("-" * 78)

    for modelo, llamadas_n, tin, tout, costo_texto in filas:
        salida.append(
            f" {modelo.ljust(ancho_modelo)}{str(llamadas_n).rjust(10)}"
            f"{format(tin, ',').rjust(16)}{format(tout, ',').rjust(15)}{costo_texto.rjust(14)}"
        )

    salida.append("-" * 78)
    salida.append(
        f" {'TOTAL'.ljust(ancho_modelo)}{str(total_llamadas).rjust(10)}"
        f"{format(total_in, ',').rjust(16)}{format(total_out, ',').rjust(15)}"
        f"{('$' + format(costo_total, '.4f')).rjust(14)}"
    )
    salida.append(linea)

    if algun_modelo_sin_precio:
        salida.append(" Nota: algún modelo no está en la tabla de precios conocida; su costo no se sumó al total.")
    salida.append(
        " Tokens reales reportados por la API de Gemini (usage_metadata), no una estimación por caracteres."
    )
    salida.append(
        " Precios oficiales: https://ai.google.dev/gemini-api/docs/pricing (consultados julio 2026)."
    )

    return "\n".join(salida)


def resumen_datos() -> dict:
    """
    Igual que resumen_texto(), pero devuelve los números en crudo (no
    texto formateado), para que el pipeline pueda guardar el costo total
    de la ejecución junto con el trabajo en MongoDB (además de imprimirlo
    en consola).
    """
    llamadas = _registro().llamadas
    por_modelo: dict[str, dict[str, float | int]] = {}
    for modelo, _etiqueta, tin, tout in llamadas:
        acumulado = por_modelo.setdefault(modelo, {"llamadas": 0, "tokens_entrada": 0, "tokens_salida": 0, "costo_usd": 0.0})
        acumulado["llamadas"] += 1
        acumulado["tokens_entrada"] += tin
        acumulado["tokens_salida"] += tout

    costo_total = 0.0
    for modelo, datos in por_modelo.items():
        precios = PRECIOS_USD_POR_MILLON.get(modelo)
        if precios is not None:
            precio_in, precio_out = precios
            datos["costo_usd"] = round(
                (datos["tokens_entrada"] / 1_000_000) * precio_in + (datos["tokens_salida"] / 1_000_000) * precio_out,
                6,
            )
            costo_total += datos["costo_usd"]

    return {
        "por_modelo": por_modelo,
        "total_llamadas": len(llamadas),
        "costo_total_usd": round(costo_total, 6),
    }


def imprimir_resumen(titulo: str = "Costos aproximados de esta ejecución") -> None:
    texto = resumen_texto(titulo)
    if texto:
        print("\n" + texto + "\n")
