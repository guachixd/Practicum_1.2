"""
clasificador.py — Detector de estructura del curso + Clasificador de material

Nuevo contenedor del pipeline (v2), necesario porque ya no hay carpetas
unidad_01/, unidad_02/... El docente sube todo suelto, así que dos cosas
que antes se resolvían "gratis" por convención de carpetas ahora hay que
resolverlas por contenido, con IA:

  1. ¿Cuántas unidades tiene el curso y cómo se llama cada una?
     -> se lee del plan docente (el archivo que lo contenga, sin
        importar su nombre de archivo), o se infiere del resto del
        material si no hay un plan docente reconocible.

  2. ¿A qué unidad pertenece cada archivo suelto que subió el docente?
     -> se decide por contenido, comparando cada archivo contra los
        títulos/temas de las unidades detectadas en el paso 1.

Ambos pasos usan el mismo cliente/reintentos que generador_recursos.py.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
from google import genai

from reintentos import llamar_con_reintentos, CuotaAgotadaError
import costos
import bd

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# En tu cuenta, gemini-2.5-flash y gemini-2.5-flash-lite tienen apenas
# 20 solicitudes por día en el nivel gratuito — con eso se acaba la
# cuota a media generación. gemini-3.1-flash-lite iguala la calidad de
# gemini-2.5-flash pero con 500 solicitudes por día en tu cuenta (25
# veces más), así que todo el pipeline usa este modelo ahora, tanto para
# tareas livianas como para generar contenido.
MODELO_CLASIFICACION = "gemini-3.1-flash-lite"

# Detectar la estructura completa de unidades de un plan docente es la
# llamada más importante de todo el pipeline: si se equivoca acá, faltan
# unidades enteras en el documento final, no solo un archivo mal
# clasificado. Antes esto usaba gemini-2.5-flash, pero como
# gemini-3.1-flash-lite iguala su calidad y tiene muchísima más cuota
# diaria disponible, no hace falta pagar el costo de cuota del modelo
# viejo para esta llamada.
MODELO_ESTRUCTURA = "gemini-3.1-flash-lite"

# Cuánto texto de cada documento se manda al detectar la estructura del
# curso. Un plan docente real puede tener decenas de miles de caracteres
# y la lista de unidades no siempre está al principio del documento, así
# que casi no se recorta — cortarlo corto es lo que antes hacía que se
# perdieran unidades enteras.
MAX_CARACTERES_POR_DOC_ESTRUCTURA = 150000
MAX_CARACTERES_TOTAL_ESTRUCTURA = 220000

# Cuánto texto del documento se manda al clasificarlo en una unidad.
MAX_CARACTERES_CLASIFICACION = 4000


def _cliente() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("No se encontró GEMINI_API_KEY en el archivo .env")
    return genai.Client(api_key=api_key)


def _llamar_gemini_json(prompt: str, etiqueta: str, modelo: str = MODELO_CLASIFICACION) -> dict:
    try:
        cliente = _cliente()
        respuesta = llamar_con_reintentos(
            lambda: cliente.models.generate_content(model=modelo, contents=prompt),
            etiqueta,
            modelo=modelo,
        )
        costos.registrar_uso(modelo, etiqueta, respuesta)
        texto = respuesta.text.strip()

        if texto.startswith("```"):
            lineas = texto.split("\n")
            texto = "\n".join(lineas[1:-1]).strip()
            if texto.endswith("```"):
                texto = texto[:-3].strip()

        return json.loads(texto)

    except CuotaAgotadaError:
        raise
    except json.JSONDecodeError as e:
        print(f"  [X] Error al decodificar JSON en '{etiqueta}': {e}")
        return {"error": "respuesta_no_json"}
    except Exception as e:
        print(f"  [X] Error de API en '{etiqueta}': {e}")
        return {"error": str(e)}


def _estructura_por_defecto(asignatura_fallback: str, codigo_fallback: str) -> dict:
    """
    Fallback si Gemini no está disponible o no logra detectar ninguna
    estructura: una sola unidad genérica que agrupa todo el material,
    para que el pipeline nunca se caiga por completo. Queda marcado
    como 'inferido' para que quede claro en el reporte de cobertura.
    """
    return {
        "asignatura": asignatura_fallback,
        "codigo": codigo_fallback,
        "unidades": [
            {"numero": 1, "titulo": "Unidad general del curso", "temas": []}
        ],
        "fuente_detectada": None,
        "inferido": True,
    }


def identificar_estructura_curso(db, documentos: list[dict], asignatura_fallback: str,
                                  codigo_fallback: str) -> dict:
    """
    Busca en TODOS los documentos subidos (sin saber de antemano cuál es
    el plan docente) la estructura de unidades del curso: cuántas hay,
    cómo se titula cada una y qué temas cubre.

    Antes de llamar a Gemini, revisa si este MISMO conjunto de archivos
    (por contenido, no por nombre) ya se resolvió antes — si el docente
    subió el mismo material de prueba varias veces, no se vuelve a gastar
    cuota en resolver algo que ya se sabe.

    Devuelve:
    {
        "asignatura": str,
        "codigo": str,
        "unidades": [{"numero": int, "titulo": str, "temas": [str, ...]}, ...],
        "fuente_detectada": str | None,   # nombre del archivo que parece ser el plan docente
        "inferido": bool                  # True si tuvo que inferirse sin plan docente explícito
    }
    """
    documentos_utilizables = [d for d in documentos if d.get("utilizable")]

    if not documentos_utilizables:
        print("  [!] No hay documentos con contenido utilizable; se usa una estructura por defecto.")
        return _estructura_por_defecto(asignatura_fallback, codigo_fallback)

    hash_conjunto = bd.hash_texto("||".join(sorted(
        f"{d['nombre']}:{bd.hash_texto(d['texto'])}" for d in documentos_utilizables
    )))

    if db is not None:
        en_cache = bd.obtener_cache_ia(db, "estructura_v5", hash_conjunto)
        if en_cache is not None:
            print("  Estructura del curso ya resuelta antes con este mismo material (caché); no se llama a la IA.")
            return en_cache

    bloques = []
    total = 0
    for d in documentos_utilizables:
        fragmento = d["texto"][:MAX_CARACTERES_POR_DOC_ESTRUCTURA]
        if total + len(fragmento) > MAX_CARACTERES_TOTAL_ESTRUCTURA:
            break
        bloques.append(f"--- ARCHIVO: {d['nombre']} ---\n{fragmento}")
        total += len(fragmento)

    material_combinado = "\n\n".join(bloques)

    prompt = f"""
Eres un asistente de diseño instruccional de la UTPL. Te paso fragmentos de
TODOS los archivos que un docente subió para su asignatura (planes docentes,
sílabos, diapositivas, guías, lecturas), cada uno identificado por su nombre
de archivo. No sabes de antemano cuál de ellos es el plan docente.

ARCHIVOS:
{material_combinado}

Tarea: identifica la estructura de unidades/temas del curso.
1. Busca el archivo que funcione como plan docente, sílabo o guía didáctica
   (suele contener nombre de la asignatura, código, y una lista de unidades
   o temas del curso, sin importar cómo se llame el archivo).
2. Si lo encuentras, extrae de ahí: nombre de la asignatura, código (si
   aparece), y la lista de unidades con su número, título y temas/subtemas.
   IMPORTANTE: revisa el documento COMPLETO de principio a fin. Muchos
   planes docentes listan las unidades en una tabla o índice, pero
   después las vuelven a desarrollar una por una en el resto del
   documento — asegúrate de listar TODAS las unidades que existan, no
   solo las primeras que encuentres. Si el plan menciona explícitamente
   cuántas unidades tiene el curso (por ejemplo "el curso consta de 8
   unidades"), tu lista final debe tener exactamente esa cantidad.
3. Si NO hay ningún documento que defina explícitamente unidades, infiere
   una división razonable de unidades a partir de los temas que sí aparecen
   repetidos en el resto del material (diapositivas, lecturas), y marca
   "inferido" como true.
4. Nunca inventes un plan docente que no exista; si infieres, que sea a
   partir de contenido real presente en los archivos.

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "asignatura": "...",
    "codigo": "...",
    "unidades": [
        {{"numero": 1, "titulo": "...", "temas": ["...", "..."]}}
    ],
    "fuente_detectada": "nombre_de_archivo.ext o null si se infirió",
    "inferido": false
}}
"""
    resultado = _llamar_gemini_json(prompt, "estructura de unidades del curso", modelo=MODELO_ESTRUCTURA)

    if "error" in resultado or not resultado.get("unidades"):
        print("  [!] No se pudo determinar la estructura del curso vía IA; se usa una estructura por defecto.")
        return _estructura_por_defecto(asignatura_fallback, codigo_fallback)

    resultado.setdefault("asignatura", asignatura_fallback)
    resultado.setdefault("codigo", codigo_fallback)
    resultado.setdefault("fuente_detectada", None)
    resultado.setdefault("inferido", False)

    if db is not None:
        bd.guardar_cache_ia(db, "estructura_v5", hash_conjunto, resultado)

    return resultado


def clasificar_documento(db, documento: dict, unidades: list[dict]) -> dict:
    """
    Decide a qué unidad pertenece un documento, comparando su contenido
    contra el título/temas de cada unidad detectada.

    Antes de llamar a Gemini, revisa el caché: si este mismo archivo
    (por contenido) ya se clasificó antes contra esta misma lista de
    unidades, reusa el resultado. Si cambia el archivo o cambia la
    estructura de unidades, el hash cambia y se reclasifica normal.

    Devuelve {"unidad": int, "justificacion": str}. "unidad" es 0 cuando
    el documento es material general del curso (plan docente, guía
    general, silabo) y no pertenece a una unidad específica.
    """
    if not documento.get("utilizable"):
        return {"unidad": 0, "justificacion": "Documento sin contenido utilizable."}

    hash_unidades = bd.hash_texto("||".join(f"{u['numero']}:{u['titulo']}" for u in unidades))
    hash_documento = bd.hash_texto(documento["texto"])
    hash_combinado = bd.hash_texto(f"{hash_documento}::{hash_unidades}")

    if db is not None:
        en_cache = bd.obtener_cache_ia(db, "clasificacion", hash_combinado)
        if en_cache is not None:
            return en_cache

    lista_unidades = "\n".join(
        f"- Unidad {u['numero']}: {u['titulo']}"
        + (f" (temas: {', '.join(u['temas'])})" if u.get("temas") else "")
        for u in unidades
    )

    fragmento = documento["texto"][:MAX_CARACTERES_CLASIFICACION]

    prompt = f"""
Eres un asistente que organiza material didáctico de un curso de la UTPL
en sus unidades correspondientes.

UNIDADES DEL CURSO:
{lista_unidades}

ARCHIVO A CLASIFICAR: {documento['nombre']}
CONTENIDO (fragmento):
{fragmento}

Tarea: decide a qué unidad pertenece este archivo, según de qué trata su
contenido comparado con el título y temas de cada unidad.

Reglas:
- Si el archivo es el plan docente, sílabo, guía general del curso, o
  cualquier documento que hable del curso completo (no de un tema
  específico), responde unidad = 0.
- Si el contenido corresponde claramente a una sola unidad, responde el
  número de esa unidad.
- Si el contenido mezcla varios temas de distintas unidades, responde el
  número de la unidad predominante (a la que corresponde la mayor parte
  del contenido).
- Si no logras determinarlo con confianza razonable, responde unidad = 0
  en vez de adivinar.

Responde ÚNICAMENTE con este JSON (sin texto adicional, sin backticks):
{{
    "unidad": 0,
    "justificacion": "..."
}}
"""
    resultado = _llamar_gemini_json(prompt, f"clasificación de '{documento['nombre']}'")

    if "error" in resultado or "unidad" not in resultado:
        print(f"  [!] No se pudo clasificar '{documento['nombre']}'; se trata como material general.")
        return {"unidad": 0, "justificacion": "No se pudo clasificar automáticamente."}

    numeros_validos = {u["numero"] for u in unidades}
    if resultado["unidad"] not in numeros_validos and resultado["unidad"] != 0:
        resultado["justificacion"] += " (número fuera de rango, reasignado a general)"
        resultado["unidad"] = 0

    if db is not None:
        bd.guardar_cache_ia(db, "clasificacion", hash_combinado, resultado)

    return resultado


def clasificar_todos_los_documentos(db, documentos: list[dict], unidades: list[dict]) -> dict[str, dict]:
    """
    Clasifica todos los documentos utilizables y devuelve un diccionario
    {nombre_archivo: {"unidad": int, "justificacion": str}}.
    """
    clasificacion = {}
    for documento in documentos:
        if not documento.get("utilizable"):
            continue
        print(f"  Clasificando '{documento['nombre']}'...")
        resultado = clasificar_documento(db, documento, unidades)
        clasificacion[documento["nombre"]] = resultado
        etiqueta = "general/plan docente" if resultado["unidad"] == 0 else f"Unidad {resultado['unidad']}"
        print(f"    -> {etiqueta}")
    return clasificacion
