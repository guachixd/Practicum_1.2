"""
bd.py — Conexión a la base de conocimiento y recursos (MongoDB local)

Corresponde al contenedor "resources.json" de tu diagrama C4, ahora respaldado
por una base de datos NoSQL real (MongoDB Community Server, local) en vez de
un archivo plano. Guarda:
  - la base de conocimiento segmentada por unidad (colección "unidades")
  - los recursos generados por Gemini por unidad, incluida la introducción
    general del curso, guardada como "unidad 0" (colección "recursos")
"""

import os
from pymongo import MongoClient
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
        print(f"Conexión a MongoDB local exitosa ({uri})")

        db = cliente["generador_recursos_didacticos"]
        return db

    except ConnectionFailure:
        print("Error: no se pudo conectar a MongoDB.")
        print("Verifica que el servicio de MongoDB Community Server esté corriendo en tu laptop.")
        return None


def guardar_unidad(db, unidad: dict):
    """
    Guarda (o actualiza) una unidad de la base de conocimiento en la
    colección 'unidades', usando el número de unidad como clave única.
    """
    coleccion = db["unidades"]
    coleccion.update_one(
        {"numero": unidad["numero"]},
        {"$set": unidad},
        upsert=True
    )


def guardar_recurso(db, numero_unidad: int, tipo_recurso: str, contenido: dict):
    """
    Guarda el recurso generado (resumen, glosario, preguntas, actividad o
    introducción) de una unidad específica en la colección 'recursos'.
    """
    coleccion = db["recursos"]
    coleccion.update_one(
        {"numero_unidad": numero_unidad, "tipo_recurso": tipo_recurso},
        {"$set": {
            "numero_unidad": numero_unidad,
            "tipo_recurso": tipo_recurso,
            "contenido": contenido
        }},
        upsert=True
    )


def obtener_recursos_unidad(db, numero_unidad: int) -> dict:
    """
    Recupera todos los recursos generados de una unidad, organizados
    por tipo_recurso. Usado por el Exportador para armar el Word final.
    """
    coleccion = db["recursos"]
    resultado = {}
    for doc in coleccion.find({"numero_unidad": numero_unidad}):
        resultado[doc["tipo_recurso"]] = doc["contenido"]
    return resultado


def guardar_introduccion(db, contenido: dict):
    """Guarda la introducción general del curso (se trata como 'unidad 0')."""
    guardar_recurso(db, 0, "introduccion", contenido)


def obtener_introduccion(db) -> dict:
    """Recupera la introducción general del curso."""
    recursos = obtener_recursos_unidad(db, 0)
    return recursos.get("introduccion", {})


# ==========================================
# BLOQUE DE PRUEBA LOCAL
# ==========================================
if __name__ == "__main__":
    print("Probando conexión a la base de datos local...")
    bd = conectar_bd()

    if bd is not None:
        print(f"Base de datos seleccionada: {bd.name}")

        unidad_ejemplo = {
            "numero": 1,
            "titulo": "Semana 1: Organización vs Arquitectura",
            "asignatura": "Arquitectura y Organización de Computadores",
            "contenido": "La arquitectura se refiere a los atributos visibles al programador..."
        }
        guardar_unidad(bd, unidad_ejemplo)
        print("Unidad de ejemplo guardada. Revisa la colección 'unidades' en Compass.")
