"""
bd.py — Base de datos (MongoDB local)

Sin sistema de cuentas: la plataforma no pide login, así que aquí no hay
colección de "docentes" ni contraseñas. Lo que se guarda:

  - trabajos: una generación de documento (datos generales, estado,
    progreso, costo real, resumen de calificaciones, historial de
    eventos, archivos subidos con su categoría, y qué recursos quedaron
    pendientes de regenerar manualmente).
  - unidades / recursos / evaluaciones: aisladas por "job_id".
  - recursos_historial: versión anterior de un recurso, guardada antes de
    sobrescribirlo cuando el docente pide regenerarlo manualmente.
  - cache_ia: resultados de clasificación/estructura ya resueltos por
    Gemini antes, indexados por el hash del contenido, para no volver a
    llamar a la API con el mismo material.
"""

import hashlib
import os
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient, ASCENDING
from pymongo.errors import ConnectionFailure
from dotenv import load_dotenv


def conectar_bd():
    """
    Establece la conexión con la instancia local de MongoDB y devuelve
    la base de datos del proyecto. Retorna None si no se pudo conectar.
    """
    load_dotenv()
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")

    try:
        cliente = MongoClient(uri, serverSelectionTimeoutMS=5000)
        cliente.admin.command("ping")

        db = cliente["generador_recursos_didacticos"]
        _asegurar_indices(db)
        return db

    except ConnectionFailure:
        print("Error: no se pudo conectar a MongoDB.")
        print("Verifica que el servicio de MongoDB Community Server esté corriendo.")
        return None


def _asegurar_indices(db):
    db["unidades"].create_index([("job_id", ASCENDING), ("numero", ASCENDING)], unique=True)
    db["recursos"].create_index(
        [("job_id", ASCENDING), ("numero_unidad", ASCENDING), ("tipo_recurso", ASCENDING)],
        unique=True,
    )
    db["evaluaciones"].create_index([("job_id", ASCENDING), ("numero_unidad", ASCENDING)], unique=True)
    db["trabajos"].create_index([("creado_en", ASCENDING)])
    db["recursos_historial"].create_index([("job_id", ASCENDING), ("numero_unidad", ASCENDING), ("tipo_recurso", ASCENDING)])
    db["cache_ia"].create_index([("tipo", ASCENDING), ("hash", ASCENDING)], unique=True)


# ==========================================
# TRABAJOS (una generación de documento)
# ==========================================

ESTADOS_TRABAJO = {
    "borrador",              # se creó pero aún no se subieron archivos / no se confirmó
    "pendiente",             # listo para procesar, en cola
    "procesando",            # el pipeline está corriendo ahora mismo
    "pausado_sin_creditos",  # se acabaron los tokens/cuota de la IA a media generación
    "pausado_manual",        # el docente presionó "Pausar" a propósito
    "completado",
    "error",
}


def crear_trabajo(db, datos: dict) -> str:
    """
    Crea un trabajo nuevo (borrador) con los datos generales que pide la
    pantalla "Nuevo documento". Devuelve el id del trabajo (string).
    """
    trabajo = {
        "nombre_docente": datos.get("nombre_docente", "").strip(),
        "carrera": datos.get("carrera", "").strip(),
        "ciclo_academico": datos.get("ciclo_academico", "").strip(),
        "periodo": datos.get("periodo", "").strip(),
        "asignatura": datos.get("asignatura", "").strip(),
        "codigo": datos.get("codigo", "").strip(),
        "marca_agua": True,
        "estado": "borrador",
        "fase_actual": None,
        "unidad_actual": None,
        "total_unidades": None,
        "mensaje": "Trabajo creado. Falta subir los archivos del curso.",
        "ruta_material": None,
        "ruta_salida": None,
        "archivos_subidos": [],
        "pausar_solicitado": False,
        "regenerar_pendientes": [],
        "costo_total_usd": None,
        "resumen_calificaciones": None,
        "historial": [],
        "creado_en": datetime.now(timezone.utc),
        "actualizado_en": datetime.now(timezone.utc),
    }
    resultado = db["trabajos"].insert_one(trabajo)
    job_id = str(resultado.inserted_id)
    registrar_evento(db, job_id, "creado", f"Asignatura: {trabajo['asignatura'] or 'sin especificar'}")
    return job_id


def _id_valido(job_id: str) -> ObjectId | None:
    try:
        return ObjectId(job_id)
    except (InvalidId, TypeError):
        return None


def obtener_trabajo(db, job_id: str) -> dict | None:
    oid = _id_valido(job_id)
    if oid is None:
        return None
    return db["trabajos"].find_one({"_id": oid})


def actualizar_trabajo(db, job_id: str, campos: dict) -> None:
    oid = _id_valido(job_id)
    if oid is None:
        return
    campos = dict(campos)
    campos.setdefault("actualizado_en", datetime.now(timezone.utc))
    db["trabajos"].update_one({"_id": oid}, {"$set": campos})


def listar_trabajos(db) -> list[dict]:
    """Todos los trabajos (en cualquier estado), del más reciente al más antiguo."""
    return list(db["trabajos"].find({}).sort("creado_en", -1))


def listar_trabajos_huerfanos(db) -> list[dict]:
    """
    Trabajos que quedaron marcados 'procesando' o 'pendiente' pero cuyo
    hilo en segundo plano ya no existe (por ejemplo, porque se reinició
    el servidor de Flask a media generación).
    """
    return list(db["trabajos"].find({"estado": {"$in": ["procesando", "pendiente"]}}).sort("creado_en", 1))


def obtener_trabajo_activo(db, excluir_job_id: str | None = None) -> dict | None:
    """
    Devuelve el trabajo más antiguo que esté 'procesando' o 'pendiente'
    (incluye una regeneración puntual en curso), si hay alguno. Evita que
    se procesen dos documentos a la vez, ya que comparten la misma cuota.
    """
    filtro = {"estado": {"$in": ["procesando", "pendiente"]}}
    if excluir_job_id is not None:
        oid = _id_valido(excluir_job_id)
        if oid is not None:
            filtro["_id"] = {"$ne": oid}
    return db["trabajos"].find_one(filtro, sort=[("creado_en", 1)])


def registrar_evento(db, job_id: str, evento: str, detalle: str | None = None) -> None:
    """
    Agrega una entrada a la línea de tiempo del trabajo (creado, subida de
    archivos, pausado, reanudado, completado, etc.), con su hora exacta.
    """
    oid = _id_valido(job_id)
    if oid is None:
        return
    entrada = {"evento": evento, "detalle": detalle, "cuando": datetime.now(timezone.utc)}
    db["trabajos"].update_one({"_id": oid}, {"$push": {"historial": entrada}})


def guardar_archivos_subidos(db, job_id: str, archivos: list[dict]) -> None:
    """
    archivos: lista de {"nombre": str, "categoria": "plan_docente" |
    "guia_didactica" | "material_extra"}. Se agrega a lo ya subido antes
    (por si se sube en más de una tanda).
    """
    oid = _id_valido(job_id)
    if oid is None or not archivos:
        return
    db["trabajos"].update_one({"_id": oid}, {"$push": {"archivos_subidos": {"$each": archivos}}})


def guardar_resultado_costos(db, job_id: str, costo_total_usd: float, resumen_calificaciones: dict) -> None:
    """Guarda el costo real y el resumen de calificaciones de la corrida junto con el trabajo."""
    actualizar_trabajo(db, job_id, {
        "costo_total_usd": costo_total_usd,
        "resumen_calificaciones": resumen_calificaciones,
    })


# ==========================================
# UNIDADES (aisladas por trabajo/job_id)
# ==========================================

def guardar_unidad(db, job_id: str, unidad: dict) -> None:
    coleccion = db["unidades"]
    documento = dict(unidad)
    documento["job_id"] = job_id
    coleccion.update_one(
        {"job_id": job_id, "numero": unidad["numero"]},
        {"$set": documento},
        upsert=True,
    )


def obtener_unidades_trabajo(db, job_id: str) -> list[dict]:
    """Unidades ya construidas para este trabajo (vacío si aún no se ha corrido el pipeline)."""
    return list(db["unidades"].find({"job_id": job_id}).sort("numero", ASCENDING))


# ==========================================
# RECURSOS (aislados por trabajo/job_id)
# ==========================================

def guardar_recurso(db, job_id: str, numero_unidad: int, tipo_recurso: str, contenido: dict) -> None:
    coleccion = db["recursos"]
    coleccion.update_one(
        {"job_id": job_id, "numero_unidad": numero_unidad, "tipo_recurso": tipo_recurso},
        {"$set": {
            "job_id": job_id,
            "numero_unidad": numero_unidad,
            "tipo_recurso": tipo_recurso,
            "contenido": contenido,
        }},
        upsert=True,
    )


def obtener_recursos_unidad(db, job_id: str, numero_unidad: int) -> dict:
    coleccion = db["recursos"]
    resultado = {}
    for doc in coleccion.find({"job_id": job_id, "numero_unidad": numero_unidad}):
        resultado[doc["tipo_recurso"]] = doc["contenido"]
    return resultado


def guardar_introduccion(db, job_id: str, contenido: dict) -> None:
    """Guarda la introducción general del curso de este trabajo (se trata como 'unidad 0')."""
    guardar_recurso(db, job_id, 0, "introduccion", contenido)


def obtener_introduccion(db, job_id: str) -> dict:
    recursos = obtener_recursos_unidad(db, job_id, 0)
    return recursos.get("introduccion", {})


def guardar_version_anterior_recurso(db, job_id: str, numero_unidad: int, tipo_recurso: str, contenido_anterior: dict) -> None:
    """
    Guarda la versión de un recurso justo antes de que se sobrescriba por
    una regeneración manual (punto 13: no se pierde lo que había antes,
    aunque todavía no haya un botón de "deshacer" en la interfaz).
    """
    db["recursos_historial"].insert_one({
        "job_id": job_id,
        "numero_unidad": numero_unidad,
        "tipo_recurso": tipo_recurso,
        "contenido": contenido_anterior,
        "reemplazado_en": datetime.now(timezone.utc),
    })


# ==========================================
# EVALUACIONES (aisladas por trabajo/job_id)
# ==========================================

def guardar_evaluacion_unidad(db, job_id: str, numero_unidad: int, reporte: dict) -> None:
    db["evaluaciones"].update_one(
        {"job_id": job_id, "numero_unidad": numero_unidad},
        {"$set": {"job_id": job_id, "numero_unidad": numero_unidad, "reporte": reporte}},
        upsert=True,
    )


def obtener_evaluacion_unidad(db, job_id: str, numero_unidad: int) -> dict | None:
    doc = db["evaluaciones"].find_one({"job_id": job_id, "numero_unidad": numero_unidad})
    return doc["reporte"] if doc else None


def obtener_evaluaciones_trabajo(db, job_id: str) -> dict[int, dict]:
    """Todas las evaluaciones de un trabajo, indexadas por número de unidad."""
    resultado = {}
    for doc in db["evaluaciones"].find({"job_id": job_id}):
        resultado[doc["numero_unidad"]] = doc["reporte"]
    return resultado


def actualizar_calificacion_recurso(db, job_id: str, numero_unidad: int, tipo_recurso: str, calificacion: dict) -> None:
    """
    Cambia la calificación de un solo recurso dentro del reporte ya
    guardado de la unidad, sin tocar los otros tres. Se usa cuando el
    docente regenera un apartado puntual desde la vista previa: no hace
    falta reevaluar toda la unidad de nuevo.
    """
    db["evaluaciones"].update_one(
        {"job_id": job_id, "numero_unidad": numero_unidad},
        {"$set": {f"reporte.detalle.{tipo_recurso}": calificacion}},
    )


# ==========================================
# CACHÉ DE CLASIFICACIÓN (ahorra llamadas repetidas a Gemini)
# ==========================================
# Si el mismo archivo (mismo contenido exacto) ya se clasificó antes, o si
# la estructura del curso ya se detectó antes con exactamente el mismo
# conjunto de archivos, se reusa el resultado guardado en vez de volver a
# llamar a la API. Se indexa por un hash del contenido, no por nombre de
# archivo (si cambia una coma, el hash cambia y se reclasifica normal).

def hash_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8", errors="ignore")).hexdigest()[:24]


def obtener_cache_ia(db, tipo: str, hash_valor: str) -> dict | None:
    doc = db["cache_ia"].find_one({"tipo": tipo, "hash": hash_valor})
    return doc["resultado"] if doc else None


def guardar_cache_ia(db, tipo: str, hash_valor: str, resultado: dict) -> None:
    db["cache_ia"].update_one(
        {"tipo": tipo, "hash": hash_valor},
        {"$set": {"tipo": tipo, "hash": hash_valor, "resultado": resultado, "guardado_en": datetime.now(timezone.utc)}},
        upsert=True,
    )
