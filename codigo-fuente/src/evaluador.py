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

from reintentos import llamar_con_reintentos, CuotaAgotadaError
import costos

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

MODELO_EVALUACION = "gemini-3.1-flash-lite"  # mismo modelo que el resto del pipeline: buena calidad y mucha más cuota diaria que gemini-2.5-flash-lite
PUNTAJE_MINIMO_APROBACION = 7


def _cliente() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("No se encontró GEMINI_API_KEY en el archivo .env")
    return genai.Client(api_key=api_key)


def evaluar_recurso(tipo_recurso: str, contenido_generado: dict, texto_fuente: str,
                     tiene_material: bool = True) -> dict:
    """
    Pide a Gemini que actúe como juez (LLM-as-a-Judge) y puntúe el recurso
    generado.

    - Si la unidad tiene material propio (tiene_material=True), evalúa
      fidelidad estricta contra el material fuente (comportamiento original).
    - Si la unidad NO tiene material propio (se generó desde el plan
      docente), no tiene sentido exigir fidelidad a una fuente vacía:
      se evalúa en cambio calidad pedagógica, coherencia con el título/temas
      de la unidad, y que el texto deje explícito que no proviene de
      material subido por el docente.

    Devuelve: {"puntaje": 0-10, "aprobado": bool, "observaciones": str}
    """
    if tiene_material:
        criterios = """1. Toda la información del recurso generado debe poder rastrearse al material fuente.
2. No debe haber datos, ejemplos o afirmaciones inventadas que no estén en la fuente.
3. El recurso debe ser coherente y estar completo según lo que se le pidió generar."""
        etiqueta_puntaje = "El puntaje va de 0 (totalmente inventado o irrelevante) a 10 (perfectamente fiel y completo)."
    else:
        criterios = """1. El contenido debe ser correcto y pedagógicamente sólido para el tema de la unidad
   (aunque no exista material fuente específico del docente).
2. Debe ser coherente con el título/temas de la unidad indicados como contexto.
3. Debe dejar explícito, en el propio texto, que se generó sin material propio del docente.
4. No debe inventar cifras, citas o datos hiperespecíficos presentados como si vinieran
   de una fuente verificada."""
        etiqueta_puntaje = "El puntaje va de 0 (irrelevante o mal fundamentado) a 10 (correcto, coherente y transparente sobre su origen)."

    prompt = f"""
Eres un auditor de calidad de contenido educativo.

TIPO DE RECURSO: {tipo_recurso}

MATERIAL FUENTE / CONTEXTO DE REFERENCIA:
{texto_fuente if texto_fuente.strip() else "(sin material propio de la unidad; ver criterios de evaluación)"}

RECURSO GENERADO A EVALUAR:
{json.dumps(contenido_generado, ensure_ascii=False)}

Evalúa con estos criterios:
{criterios}

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "puntaje": 0,
    "observaciones": "Explicación breve de por qué se dio ese puntaje."
}}

{etiqueta_puntaje}
"""

    try:
        cliente = _cliente()
        respuesta = llamar_con_reintentos(
            lambda: cliente.models.generate_content(model=MODELO_EVALUACION, contents=prompt),
            f"evaluación de '{tipo_recurso}'",
        )
        costos.registrar_uso(MODELO_EVALUACION, f"evaluación de '{tipo_recurso}'", respuesta)
        texto = respuesta.text.strip()

        if texto.startswith("```"):
            lineas = texto.split("\n")
            texto = "\n".join(lineas[1:-1]).strip()
            if texto.endswith("```"):
                texto = texto[:-3].strip()

        resultado = json.loads(texto)
        resultado["aprobado"] = resultado.get("puntaje", 0) >= PUNTAJE_MINIMO_APROBACION
        return resultado

    except CuotaAgotadaError:
        raise
    except Exception as e:
        print(f"  [X] Error evaluando '{tipo_recurso}': {e}")
        return {"puntaje": 0, "aprobado": False, "observaciones": f"Error de sistema: {e}"}


def evaluar_unidad_completa(unidad: dict, recursos: dict) -> dict:
    """
    Evalúa los cuatro recursos de una unidad y devuelve un reporte con el
    detalle de cada uno más cuáles necesitan reformularse (puntaje < 7).

    Se conserva esta versión (una llamada por recurso) para cuando hay
    que reevaluar solo un recurso puntual, por ejemplo después de una
    reformulación o de una regeneración manual pedida por el docente.
    Para la primera evaluación de una unidad completa se usa
    evaluar_recursos_unidad, que hace todo en una sola llamada.
    """
    reporte = {}
    for tipo_recurso, contenido in recursos.items():
        print(f"  Evaluando '{tipo_recurso}' de la Unidad {unidad['numero']}...")
        reporte[tipo_recurso] = evaluar_recurso(
            tipo_recurso, contenido, unidad["contenido"], unidad["tiene_material"]
        )
        _imprimir_puntaje(unidad["numero"], tipo_recurso, reporte[tipo_recurso])

    recursos_a_reformular = [t for t, r in reporte.items() if not r["aprobado"]]
    return {
        "detalle": reporte,
        "necesita_reformular": recursos_a_reformular
    }


def _imprimir_puntaje(numero_unidad: int, tipo_recurso: str, calificacion: dict) -> None:
    """Muestra en consola qué nota le puso la IA a cada apartado, para que se vea de un vistazo."""
    marca = "OK" if calificacion.get("aprobado") else "reformular"
    print(f"    Unidad {numero_unidad} · {tipo_recurso}: {calificacion.get('puntaje', 0)}/10 ({marca})")


def evaluar_recursos_unidad(unidad: dict, recursos: dict) -> dict:
    """
    Evalúa los cuatro recursos de la unidad en UNA sola llamada a Gemini,
    en vez de 4 evaluaciones separadas. Junto con generar_recursos_unidad
    de generador_recursos.py, esto es lo que baja el pipeline de 8
    llamadas por unidad a solo 2.

    Devuelve el mismo formato que evaluar_unidad_completa (para que el
    resto del pipeline no tenga que distinguir cuál se usó).
    """
    prompt = f"""
Eres un auditor de calidad de contenido educativo.

MATERIAL FUENTE / CONTEXTO DE REFERENCIA:
{unidad["contenido"] if unidad["contenido"].strip() else "(sin material propio de la unidad; ver criterios de evaluación)"}

Vas a evaluar CUATRO recursos generados para la unidad "{unidad['titulo']}",
todos en la misma respuesta. Para cada uno, da un puntaje de 0 a 10 y una
observación breve.

{"Como la unidad SÍ tiene material propio, toda la información del recurso debe poder rastrearse a ese material: no debe haber datos, ejemplos o afirmaciones inventadas que no estén en la fuente." if unidad["tiene_material"] else "Como la unidad NO tiene material propio (se generó desde el plan docente), evalúa que el contenido sea correcto y pedagógicamente sólido, coherente con el título/temas de la unidad, que deje explícito que no viene de material del docente, y que no invente cifras o citas presentadas como si fueran de una fuente verificada."}

RESUMEN GENERADO:
{json.dumps(recursos.get("resumen", {}), ensure_ascii=False)}

GLOSARIO GENERADO:
{json.dumps(recursos.get("glosario", {}), ensure_ascii=False)}

PREGUNTAS GENERADAS:
{json.dumps(recursos.get("preguntas", {}), ensure_ascii=False)}

ACTIVIDAD GENERADA:
{json.dumps(recursos.get("actividad", {}), ensure_ascii=False)}

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "resumen": {{"puntaje": 0, "observaciones": "..."}},
    "glosario": {{"puntaje": 0, "observaciones": "..."}},
    "preguntas": {{"puntaje": 0, "observaciones": "..."}},
    "actividad": {{"puntaje": 0, "observaciones": "..."}}
}}
"""
    try:
        cliente = _cliente()
        respuesta = llamar_con_reintentos(
            lambda: cliente.models.generate_content(model=MODELO_EVALUACION, contents=prompt),
            f"evaluación de la unidad {unidad['numero']}",
        )
        costos.registrar_uso(MODELO_EVALUACION, f"evaluación de la unidad {unidad['numero']}", respuesta)
        texto = respuesta.text.strip()
        if texto.startswith("```"):
            lineas = texto.split("\n")
            texto = "\n".join(lineas[1:-1]).strip()
            if texto.endswith("```"):
                texto = texto[:-3].strip()
        resultado = json.loads(texto)
    except CuotaAgotadaError:
        raise
    except Exception as e:
        print(f"  [X] Error evaluando la unidad {unidad['numero']} de una vez: {e}")
        resultado = {}

    reporte = {}
    for tipo_recurso in recursos:
        calificacion = resultado.get(tipo_recurso) if isinstance(resultado, dict) else None
        if not calificacion or "puntaje" not in calificacion:
            # esta pieza no vino bien en el JSON conjunto; se evalúa aparte,
            # nada más esta, no hace falta repetir las otras 3
            print(f"  '{tipo_recurso}' no vino bien en la evaluación conjunta, se evalúa aparte...")
            calificacion = evaluar_recurso(
                tipo_recurso, recursos[tipo_recurso], unidad["contenido"], unidad["tiene_material"]
            )
        else:
            calificacion["aprobado"] = calificacion.get("puntaje", 0) >= PUNTAJE_MINIMO_APROBACION
        reporte[tipo_recurso] = calificacion
        _imprimir_puntaje(unidad["numero"], tipo_recurso, calificacion)

    recursos_a_reformular = [t for t, r in reporte.items() if not r["aprobado"]]
    return {
        "detalle": reporte,
        "necesita_reformular": recursos_a_reformular,
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
