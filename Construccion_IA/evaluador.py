"""
evaluador.py — Evaluador Automático

Corresponde al contenedor "Evaluador Automático" de tu diagrama C4.
Envía cada recurso generado a Gemini para que lo puntúe (0-10) contra el
material fuente. Si el puntaje es menor a 7, señala que el prompt debe
reformularse (según tu diagrama: evaluador -> promptgen).
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
from google import genai

from reintentos import llamar_con_reintentos

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

MODELO_EVALUACION = "gemini-2.5-flash-lite"  # modelo más ligero, suficiente para juzgar
PUNTAJE_MINIMO_APROBACION = 7


def _cliente() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("No se encontró GEMINI_API_KEY en el archivo .env")
    return genai.Client(api_key=api_key)


def evaluar_recurso(tipo_recurso: str, contenido_generado: dict, texto_fuente: str) -> dict:
    """
    Pide a Gemini que actúe como juez (LLM-as-a-Judge) y puntúe el recurso
    generado contra el material fuente de la unidad.

    Devuelve: {"puntaje": 0-10, "aprobado": bool, "observaciones": str}
    """
    prompt = f"""
Eres un auditor de calidad de contenido educativo. Tu tarea es verificar si
un recurso generado por IA es fiel al material fuente, sin alucinaciones ni
información inventada.

TIPO DE RECURSO: {tipo_recurso}

MATERIAL FUENTE (verdad de referencia):
{texto_fuente}

RECURSO GENERADO A EVALUAR:
{json.dumps(contenido_generado, ensure_ascii=False)}

Evalúa con estos criterios:
1. Toda la información del recurso generado debe poder rastrearse al material fuente.
2. No debe haber datos, ejemplos o afirmaciones inventadas que no estén en la fuente.
3. El recurso debe ser coherente y estar completo según lo que se le pidió generar.

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "puntaje": 0,
    "observaciones": "Explicación breve de por qué se dio ese puntaje."
}}

El puntaje va de 0 (totalmente inventado o irrelevante) a 10 (perfectamente fiel y completo).
"""

    try:
        cliente = _cliente()
        respuesta = llamar_con_reintentos(
            lambda: cliente.models.generate_content(model=MODELO_EVALUACION, contents=prompt),
            f"evaluación de '{tipo_recurso}'",
        )
        texto = respuesta.text.strip()

        if texto.startswith("```"):
            lineas = texto.split("\n")
            texto = "\n".join(lineas[1:-1]).strip()
            if texto.endswith("```"):
                texto = texto[:-3].strip()

        resultado = json.loads(texto)
        resultado["aprobado"] = resultado.get("puntaje", 0) >= PUNTAJE_MINIMO_APROBACION
        return resultado

    except Exception as e:
        print(f"  [X] Error evaluando '{tipo_recurso}': {e}")
        return {"puntaje": 0, "aprobado": False, "observaciones": f"Error de sistema: {e}"}


def evaluar_unidad_completa(unidad: dict, recursos: dict) -> dict:
    """
    Evalúa los cuatro recursos de una unidad y devuelve un reporte con el
    detalle de cada uno más cuáles necesitan reformularse (puntaje < 7).
    """
    reporte = {}
    for tipo_recurso, contenido in recursos.items():
        print(f"  Evaluando '{tipo_recurso}' de la Unidad {unidad['numero']}...")
        reporte[tipo_recurso] = evaluar_recurso(tipo_recurso, contenido, unidad["contenido"])

    recursos_a_reformular = [t for t, r in reporte.items() if not r["aprobado"]]
    return {
        "detalle": reporte,
        "necesita_reformular": recursos_a_reformular
    }


# ==========================================
# BLOQUE DE PRUEBA LOCAL (con mocks, sin llamar a Gemini todavía)
# ==========================================
if __name__ == "__main__":
    texto_fuente = (
        "La memoria principal (RAM) es volátil y pierde su información al "
        "apagarse el equipo. Los discos SSD, en cambio, utilizan memoria "
        "flash no volátil para el almacenamiento persistente."
    )

    resumen_fiel = {
        "parrafo_1": "La RAM es volátil y pierde los datos al apagar el equipo.",
        "parrafo_2": "Los SSD usan memoria flash no volátil para persistencia."
    }

    resumen_con_alucinacion = {
        "parrafo_1": "La RAM es volátil, pero el caché L1/L2 acelera el acceso.",
        "parrafo_2": "Los SSD reemplazaron a los discos HDD magnéticos por velocidad."
    }

    if not os.getenv("GEMINI_API_KEY"):
        print("No hay GEMINI_API_KEY configurada — no se puede probar el evaluador todavía.")
        print("Cuando tengas tu API key en el .env, corre este script de nuevo.")
    else:
        print("--- PRUEBA 1: resumen fiel a la fuente ---")
        print(json.dumps(evaluar_recurso("resumen", resumen_fiel, texto_fuente), indent=2, ensure_ascii=False))

        print("\n--- PRUEBA 2: resumen con alucinación ---")
        print(json.dumps(evaluar_recurso("resumen", resumen_con_alucinacion, texto_fuente), indent=2, ensure_ascii=False))
