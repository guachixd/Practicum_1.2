"""
generador_recursos.py — Generador de Recursos

Corresponde al contenedor "Generador de Recursos" de tu diagrama C4.
Arma los prompts estructurados por unidad y tipo de recurso, y llama a la
API de Gemini para generar:
  - introducción general del curso (una sola vez, no por unidad)
  - resumen ejecutivo
  - glosario
  - preguntas de comprensión
  - actividad de reflexión
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
from google import genai

from reintentos import llamar_con_reintentos

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

MODELO_GENERACION = "gemini-2.5-flash"  # ajusta al modelo disponible en tu API key


def _cliente() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("No se encontró GEMINI_API_KEY en el archivo .env")
    return genai.Client(api_key=api_key)


def _llamar_gemini_json(prompt: str, etiqueta: str) -> dict:
    """
    Llama a Gemini con un prompt que exige respuesta JSON, limpia posibles
    backticks de markdown y parsea el resultado. Si algo falla, devuelve
    un dict con clave 'error' en vez de lanzar una excepción, para que el
    pipeline pueda seguir con las demás unidades/recursos.

    Los errores transitorios (429 cuota agotada, 503 modelo sobrecargado)
    se reintentan automáticamente esperando el tiempo que la propia API
    sugiere (ver reintentos.py) antes de rendirse.
    """
    try:
        cliente = _cliente()
        respuesta = llamar_con_reintentos(
            lambda: cliente.models.generate_content(model=MODELO_GENERACION, contents=prompt),
            etiqueta,
        )
        texto = respuesta.text.strip()

        if texto.startswith("```"):
            lineas = texto.split("\n")
            texto = "\n".join(lineas[1:-1]).strip()
            if texto.endswith("```"):
                texto = texto[:-3].strip()

        return json.loads(texto)

    except json.JSONDecodeError as e:
        print(f"  [X] Error al decodificar JSON en '{etiqueta}': {e}")
        return {"error": "respuesta_no_json"}
    except Exception as e:
        print(f"  [X] Error de API en '{etiqueta}': {e}")
        return {"error": str(e)}


def generar_introduccion_general(material_general: str, asignatura: str, codigo: str) -> dict:
    """
    Genera una introducción general de la asignatura a partir del material
    general del curso (todo lo que estaba en la raíz de data/material/,
    sin importar el nombre de archivo). Se usa una sola vez para todo el
    documento, no por unidad.
    """
    prompt = f"""
Eres un asistente de diseño instruccional para la asignatura "{asignatura}" ({codigo}) de la UTPL.

MATERIAL GENERAL DEL CURSO:
{material_general}

Tarea: escribe una introducción general de la asignatura, pensada como la
primera página de un documento de recursos didácticos para los estudiantes.

Reglas:
- 2 a 3 párrafos breves.
- Explica de qué trata la asignatura, qué se espera que el estudiante logre,
  y cómo está organizado el curso (si el material lo indica).
- Basa todo ÚNICAMENTE en el material dado; no inventes objetivos ni
  contenidos que no estén mencionados.
- Si el material no alcanza para una introducción completa, escribe lo que
  sí se pueda sustentar y sé breve.

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "introduccion": "..."
}}
"""
    return _llamar_gemini_json(prompt, "introducción general del curso")


def generar_resumen_ejecutivo(unidad: dict) -> dict:
    prompt = f"""
Eres un asistente de diseño instruccional para la asignatura "{unidad['asignatura']}"
({unidad['codigo']}) de la UTPL.

MATERIAL DE LA UNIDAD "{unidad['titulo']}":
{unidad['contenido']}

Tarea: genera un resumen ejecutivo de esta unidad, escrito para un estudiante
que ya leyó el material y quiere repasar los conceptos clave antes de una
evaluación.

Reglas:
- Exactamente 2 párrafos (parrafo_1 y parrafo_2).
- Ningún párrafo debe superar las cuatro líneas de extensión.
- Entre los dos párrafos deben quedar cubiertos como mínimo los tres
  conceptos más importantes de la unidad.
- Cada párrafo debe basarse ÚNICAMENTE en información presente en el
  material. No agregues datos, ejemplos o cifras que no estén en el texto.
- Si el material está vacío o es insuficiente, devuelve cadenas vacías en
  "parrafo_1" y "parrafo_2" en vez de inventar contenido.

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "parrafo_1": "...",
    "parrafo_2": "..."
}}
"""
    return _llamar_gemini_json(prompt, f"resumen unidad {unidad['numero']}")


def generar_glosario(unidad: dict) -> dict:
    prompt = f"""
Eres un asistente de diseño instruccional para la asignatura "{unidad['asignatura']}"
({unidad['codigo']}) de la UTPL.

MATERIAL DE LA UNIDAD "{unidad['titulo']}":
{unidad['contenido']}

Tarea: extrae un glosario de términos técnicos específicos de esta unidad.

Reglas:
- Entre 8 y 10 términos (menos solo si el material es demasiado corto para
  sustentar esa cantidad; nunca inventes términos que no aparezcan en el texto).
- Ordena los términos de más a menos fundamental para la unidad.
- Definición de máximo 2 oraciones, tomada o parafraseada del material,
  no de conocimiento externo.
- No incluyas términos genéricos que no sean propios de la asignatura.

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "terminos": [
        {{"termino": "...", "definicion": "..."}}
    ]
}}
"""
    return _llamar_gemini_json(prompt, f"glosario unidad {unidad['numero']}")


def generar_preguntas_comprension(unidad: dict) -> dict:
    prompt = f"""
Eres un asistente de diseño instruccional para la asignatura "{unidad['asignatura']}"
({unidad['codigo']}) de la UTPL.

MATERIAL DE LA UNIDAD "{unidad['titulo']}":
{unidad['contenido']}

Tarea: genera exactamente 5 preguntas de comprensión sobre esta unidad,
organizadas en tres niveles de la taxonomía de Bloom:
- 2 preguntas de nivel "facil" (recordar / comprender): piden un dato o
  definición explícita del material.
- 2 preguntas de nivel "media" (aplicar / analizar): piden relacionar dos
  ideas del material o aplicar un concepto a un caso dentro del mismo texto.
- 1 pregunta de nivel "dificil" (evaluar / crear): pide juzgar, comparar
  críticamente o proponer algo a partir de los conceptos de la unidad.

Reglas:
- Todas deben poder responderse completamente con el material dado, sin
  información externa.
- Respeta el orden: primero las 2 fáciles, luego las 2 medias, y al final
  la difícil.
- La "respuesta_esperada" debe ser breve, no ambigua y verificable contra
  el material.
- Si el material es insuficiente para sostener los 3 niveles, genera las
  preguntas que sí se puedan sustentar y deja el resto fuera de la lista
  en vez de inventar contenido.

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "preguntas": [
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "facil"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "facil"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "media"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "media"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "dificil"}}
    ]
}}
"""
    return _llamar_gemini_json(prompt, f"preguntas unidad {unidad['numero']}")


def generar_actividad_reflexion(unidad: dict) -> dict:
    prompt = f"""
Eres un asistente de diseño instruccional para la asignatura "{unidad['asignatura']}"
({unidad['codigo']}) de la UTPL.

MATERIAL DE LA UNIDAD "{unidad['titulo']}":
{unidad['contenido']}

Tarea: diseña una actividad de reflexión de cierre para esta unidad.

Reglas:
- Debe conectar un concepto del material con una situación práctica o real.
- Debe poder completarse en 20-30 minutos.
- Indica claramente qué debe entregar o responder el estudiante.

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "consigna": "...",
    "entregable_esperado": "..."
}}
"""
    return _llamar_gemini_json(prompt, f"actividad unidad {unidad['numero']}")


def generar_todos_los_recursos(unidad: dict) -> dict:
    """
    Genera los cuatro tipos de recurso para una unidad y los devuelve
    en un solo diccionario, listo para guardarse en la base de datos.
    """
    if not unidad.get("tiene_material"):
        print(f"  [!] Unidad {unidad['numero']} no tiene material, se omite la generación.")
        return {}

    print(f"Generando recursos para Unidad {unidad['numero']}...")
    return {
        "resumen": generar_resumen_ejecutivo(unidad),
        "glosario": generar_glosario(unidad),
        "preguntas": generar_preguntas_comprension(unidad),
        "actividad": generar_actividad_reflexion(unidad),
    }


# ==========================================
# BLOQUE DE PRUEBA LOCAL
# ==========================================
if __name__ == "__main__":
    unidad_prueba = {
        "numero": 1,
        "titulo": "Unidad 1: Organización vs Arquitectura",
        "asignatura": "Arquitectura y Organización de Computadores",
        "codigo": "COMP_2010",
        "contenido": (
            "La arquitectura se refiere a los atributos visibles al programador "
            "(set de instrucciones, tamaño de palabra). La organización se refiere "
            "a las unidades operativas y sus interconexiones físicas que implementan "
            "la arquitectura (señales de control, interfaces, memoria)."
        ),
        "tiene_material": True
    }

    if not os.getenv("GEMINI_API_KEY"):
        print("No hay GEMINI_API_KEY configurada en .env — solo se muestra el prompt de ejemplo, sin llamar a la API.")
    else:
        recursos = generar_todos_los_recursos(unidad_prueba)
        print(json.dumps(recursos, indent=2, ensure_ascii=False))
