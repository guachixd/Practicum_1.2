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

Cambio de fondo (v2): antes, una unidad sin material propio (sin
diapositivas subidas para ese tema) se saltaba por completo. Ahora
SIEMPRE se genera la documentación completa de cada unidad definida en
el plan docente, tenga o no material propio:
  - Si la unidad tiene material (unidad["contenido"] no vacío): se genera
    con las mismas reglas estrictas de siempre (basado ÚNICAMENTE en el
    material, sin inventar nada que no esté ahí).
  - Si la unidad NO tiene material propio: se genera usando el título y
    los temas de la unidad (extraídos del plan docente) más el contexto
    general del curso, apoyándose en conocimiento general y pedagógico
    del tema — dejando explícito en el propio contenido generado que no
    proviene de material subido por el docente, para que el exportador
    pueda marcarlo y no se confunda con contenido verificado contra fuente.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
from google import genai

from reintentos import llamar_con_reintentos, CuotaAgotadaError
import costos

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

MODELO_GENERACION = "gemini-3.1-flash-lite"  # iguala la calidad de gemini-2.5-flash, con muchísima más cuota diaria en el nivel gratuito


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
            modelo=MODELO_GENERACION,
        )
        costos.registrar_uso(MODELO_GENERACION, etiqueta, respuesta)
        texto = respuesta.text.strip()

        if texto.startswith("```"):
            lineas = texto.split("\n")
            texto = "\n".join(lineas[1:-1]).strip()
            if texto.endswith("```"):
                texto = texto[:-3].strip()

        return json.loads(texto)

    except CuotaAgotadaError:
        # No se atrapa como un error más: debe subir hasta el pipeline para
        # que pause el trabajo del docente de forma ordenada (ver pipeline.py).
        raise
    except json.JSONDecodeError as e:
        print(f"  [X] Error al decodificar JSON en '{etiqueta}': {e}")
        return {"error": "respuesta_no_json"}
    except Exception as e:
        print(f"  [X] Error de API en '{etiqueta}': {e}")
        return {"error": str(e)}


def _bloque_material_o_fallback(unidad: dict) -> tuple[str, str]:
    """
    Devuelve (bloque_material, instruccion_fidelidad) según si la unidad
    tiene material propio subido o no.

    - Con material: el bloque es el contenido real, y la instrucción exige
      basarse ÚNICAMENTE en él (igual que antes).
    - Sin material: el bloque es el título + temas del plan docente + el
      contexto general del curso, y la instrucción autoriza usar
      conocimiento general del tema, dejándolo explícito en el texto
      generado (para que no se confunda con contenido verificado contra
      material del docente).
    """
    if unidad["tiene_material"]:
        bloque = unidad["contenido"]
        instruccion = (
            "Basa todo ÚNICAMENTE en el material de la unidad dado arriba. "
            "No agregues datos, ejemplos o cifras que no estén en el texto."
        )
        return bloque, instruccion

    temas = ", ".join(unidad.get("temas", [])) or "(sin temas específicos listados en el plan docente)"
    bloque = (
        f"El docente no subió material propio (diapositivas, lecturas, etc.) para esta unidad.\n"
        f"Título de la unidad según el plan docente: {unidad['titulo']}\n"
        f"Temas de la unidad según el plan docente: {temas}\n\n"
        f"CONTEXTO GENERAL DEL CURSO (plan docente / guías):\n{unidad['contexto_curso']}"
    )
    instruccion = (
        "No hay material específico subido para esta unidad. Genera el contenido apoyándote en "
        "conocimiento general y pedagógicamente sólido sobre el título y los temas de la unidad "
        "(consistente con el contexto general del curso), como lo haría un docente universitario "
        "preparando material nuevo para ese tema. Que el contenido sea correcto y estándar para "
        "la materia, sin inventar datos falsos ni citar fuentes o cifras específicas que no puedas "
        "sustentar. Empieza el primer párrafo o elemento generado dejando en claro, en una frase breve, "
        "que este contenido se generó a partir del título y temas de la unidad, sin material propio "
        "del docente."
    )
    return bloque, instruccion


def generar_introduccion_general(material_general: str, asignatura: str, codigo: str) -> dict:
    """
    Genera una introducción general de la asignatura a partir del material
    general del curso (plan docente, guías, y cualquier archivo que el
    clasificador no pudo asociar a una unidad específica). Se usa una sola
    vez para todo el documento, no por unidad.
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
    bloque, instruccion = _bloque_material_o_fallback(unidad)
    prompt = f"""
Eres un asistente de diseño instruccional para la asignatura "{unidad['asignatura']}"
({unidad['codigo']}) de la UTPL.

MATERIAL DE LA UNIDAD "{unidad['titulo']}":
{bloque}

Tarea: genera un resumen ejecutivo de esta unidad, escrito para un estudiante
que quiere repasar los conceptos clave antes de una evaluación.

Reglas:
- Exactamente 2 párrafos (parrafo_1 y parrafo_2), pero bien desarrollados:
  hasta 7-8 líneas cada uno, no un resumen apretado de 2-3 líneas.
- Entre los dos párrafos deben quedar cubiertos como mínimo 5 conceptos
  importantes de la unidad, explicados con algo de detalle (no solo
  mencionados de pasada).
- {instruccion}

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "parrafo_1": "...",
    "parrafo_2": "..."
}}
"""
    return _llamar_gemini_json(prompt, f"resumen unidad {unidad['numero']}")


def generar_glosario(unidad: dict) -> dict:
    bloque, instruccion = _bloque_material_o_fallback(unidad)
    prompt = f"""
Eres un asistente de diseño instruccional para la asignatura "{unidad['asignatura']}"
({unidad['codigo']}) de la UTPL.

MATERIAL DE LA UNIDAD "{unidad['titulo']}":
{bloque}

Tarea: arma un glosario de términos técnicos específicos de esta unidad.

Reglas:
- Entre 12 y 15 términos (menos solo si de verdad no se puede sustentar esa
  cantidad con el material disponible).
- Ordena los términos de más a menos fundamental para la unidad.
- Definición de 1 a 3 oraciones, clara y completa (no una sola frase corta).
- No incluyas términos genéricos que no sean propios de la asignatura.
- {instruccion}

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "terminos": [
        {{"termino": "...", "definicion": "..."}}
    ]
}}
"""
    return _llamar_gemini_json(prompt, f"glosario unidad {unidad['numero']}")


def generar_preguntas_comprension(unidad: dict) -> dict:
    bloque, instruccion = _bloque_material_o_fallback(unidad)
    prompt = f"""
Eres un asistente de diseño instruccional para la asignatura "{unidad['asignatura']}"
({unidad['codigo']}) de la UTPL.

MATERIAL DE LA UNIDAD "{unidad['titulo']}":
{bloque}

Tarea: genera exactamente 7 preguntas de comprensión sobre esta unidad,
organizadas en tres niveles de la taxonomía de Bloom:
- 3 preguntas de nivel "facil" (recordar / comprender).
- 3 preguntas de nivel "media" (aplicar / analizar).
- 1 pregunta de nivel "dificil" (evaluar / crear).

Reglas:
- Respeta el orden: primero las 3 fáciles, luego las 3 medias, y al final
  la difícil.
- La "respuesta_esperada" debe ser completa (2-3 oraciones), no una sola
  palabra o frase suelta.
- {instruccion}

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "preguntas": [
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "facil"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "facil"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "facil"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "media"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "media"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "media"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "dificil"}}
    ]
}}
"""
    return _llamar_gemini_json(prompt, f"preguntas unidad {unidad['numero']}")


def generar_actividad_reflexion(unidad: dict) -> dict:
    bloque, instruccion = _bloque_material_o_fallback(unidad)
    prompt = f"""
Eres un asistente de diseño instruccional para la asignatura "{unidad['asignatura']}"
({unidad['codigo']}) de la UTPL.

MATERIAL DE LA UNIDAD "{unidad['titulo']}":
{bloque}

Tarea: diseña una actividad de reflexión de cierre para esta unidad, con
un poco más de desarrollo que una simple pregunta suelta.

Reglas:
- Debe conectar un concepto de la unidad con una situación práctica o real,
  descrita con suficiente contexto (no una sola línea).
- Debe poder completarse en 30-45 minutos.
- Indica claramente qué debe entregar o responder el estudiante, y qué
  puntos debería tocar esa entrega para considerarse completa.
- {instruccion}

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "consigna": "...",
    "entregable_esperado": "..."
}}
"""
    return _llamar_gemini_json(prompt, f"actividad unidad {unidad['numero']}")


def generar_todos_los_recursos(unidad: dict) -> dict:
    """
    Genera los cuatro tipos de recurso para una unidad y los devuelve en
    un solo diccionario, listo para guardarse en la base de datos.

    Ya NO se salta si la unidad no tiene material propio: siempre se
    genera algo, usando el título/temas del plan docente como base
    cuando no hay material subido (ver _bloque_material_o_fallback).
    """
    if unidad["tiene_material"]:
        print(f"Generando recursos para Unidad {unidad['numero']} (con material propio)...")
    else:
        print(f"Generando recursos para Unidad {unidad['numero']} "
              f"(SIN material propio; se usa el plan docente como base)...")

    return {
        "resumen": generar_resumen_ejecutivo(unidad),
        "glosario": generar_glosario(unidad),
        "preguntas": generar_preguntas_comprension(unidad),
        "actividad": generar_actividad_reflexion(unidad),
    }


GENERADORES_INDIVIDUALES = {
    "resumen": generar_resumen_ejecutivo,
    "glosario": generar_glosario,
    "preguntas": generar_preguntas_comprension,
    "actividad": generar_actividad_reflexion,
}


def generar_recursos_unidad(unidad: dict) -> dict:
    """
    Pide los 4 recursos de la unidad en UNA sola llamada a Gemini, en vez
    de 4 llamadas por separado. Esto es lo que más cuota ahorra en todo
    el pipeline: antes eran 4 llamadas por unidad solo para generar, y
    con esto queda en 1.

    Si algún recurso vino incompleto o mal formado dentro del JSON
    conjunto, no se descarta todo: se pide aparte solo esa pieza puntual
    con su función individual de siempre.
    """
    bloque, instruccion = _bloque_material_o_fallback(unidad)
    prompt = f"""
Eres un asistente de diseño instruccional para la asignatura "{unidad['asignatura']}"
({unidad['codigo']}) de la UTPL.

MATERIAL DE LA UNIDAD "{unidad['titulo']}":
{bloque}

Tarea: genera estos 4 recursos didácticos de la unidad, TODOS en la misma
respuesta:

1. RESUMEN: exactamente 2 párrafos (parrafo_1 y parrafo_2), bien
   desarrollados (hasta 7-8 líneas cada uno), cubriendo entre los dos al
   menos 5 conceptos importantes de la unidad con algo de detalle.

2. GLOSARIO: entre 12 y 15 términos técnicos propios de la unidad, del más
   al menos fundamental, con definición de 1 a 3 oraciones cada uno.

3. PREGUNTAS: exactamente 7 preguntas de comprensión según la taxonomía
   de Bloom (3 de nivel "facil", 3 de nivel "media", 1 de nivel
   "dificil", en ese orden), cada una con su respuesta_esperada completa
   (2-3 oraciones).

4. ACTIVIDAD: una actividad de reflexión de cierre que conecte un
   concepto de la unidad con una situación práctica descrita con
   contexto, completable en 30-45 minutos, indicando claramente qué debe
   entregar el estudiante y qué puntos debería tocar esa entrega.

Regla para las 4: {instruccion}

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "resumen": {{"parrafo_1": "...", "parrafo_2": "..."}},
    "glosario": {{"terminos": [{{"termino": "...", "definicion": "..."}}]}},
    "preguntas": {{"preguntas": [
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "facil"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "facil"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "facil"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "media"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "media"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "media"}},
        {{"pregunta": "...", "respuesta_esperada": "...", "nivel": "dificil"}}
    ]}},
    "actividad": {{"consigna": "...", "entregable_esperado": "..."}}
}}
"""
    if unidad["tiene_material"]:
        print(f"Generando recursos de la Unidad {unidad['numero']} en una sola llamada (con material propio)...")
    else:
        print(f"Generando recursos de la Unidad {unidad['numero']} en una sola llamada (sin material propio)...")

    resultado = _llamar_gemini_json(prompt, f"recursos unidad {unidad['numero']}")

    recursos = {}
    for tipo, generar_individual in GENERADORES_INDIVIDUALES.items():
        contenido = resultado.get(tipo) if isinstance(resultado, dict) else None
        vino_mal = not contenido or not isinstance(contenido, dict) or "error" in contenido
        if vino_mal:
            print(f"  '{tipo}' no vino bien en la llamada conjunta, se pide aparte...")
            contenido = generar_individual(unidad)
        recursos[tipo] = contenido

    return recursos


# ==========================================
# BLOQUE DE PRUEBA LOCAL
# ==========================================
if __name__ == "__main__":
    unidad_prueba = {
        "numero": 1,
        "titulo": "Unidad 1: Organización vs Arquitectura",
        "temas": ["Arquitectura de computadores", "Organización de computadores"],
        "asignatura": "Arquitectura y Organización de Computadores",
        "codigo": "COMP_2010",
        "contenido": (
            "La arquitectura se refiere a los atributos visibles al programador "
            "(set de instrucciones, tamaño de palabra). La organización se refiere "
            "a las unidades operativas y sus interconexiones físicas que implementan "
            "la arquitectura (señales de control, interfaces, memoria)."
        ),
        "contexto_curso": "",
        "tiene_material": True
    }

    if not os.getenv("GEMINI_API_KEY"):
        print("No hay GEMINI_API_KEY configurada en .env — solo se muestra el prompt de ejemplo, sin llamar a la API.")
    else:
        recursos = generar_todos_los_recursos(unidad_prueba)
        print(json.dumps(recursos, indent=2, ensure_ascii=False))
