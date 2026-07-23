"""
main.py — Orquestador de línea de comandos (uso local / pruebas)

Este archivo se conserva para poder correr el pipeline completo desde la
terminal, tal como antes. Para el uso normal de los docentes, la vía
recomendada ahora es la interfaz web (ver webapp/app.py), que usa
pipeline.py (mismo flujo, pero resumible y aislado por trabajo/docente).

Ejecuta el pipeline completo:
  extractor -> base_conocimiento (clasificador) -> bd (guarda unidades)
  -> introducción general -> generador_recursos (SIEMPRE, con o sin material)
  -> bd (guarda recursos) -> evaluador (reformula si <7)
  -> exportador -> docx final con marca de agua
"""

import os
import sys

from extractor import procesar_material_curso
from base_conocimiento import construir_unidades, resumen_cobertura
from generador_recursos import generar_introduccion_general, generar_recursos_unidad, GENERADORES_INDIVIDUALES
from evaluador import evaluar_recursos_unidad
from exportador import exportar_documento_final
from reintentos import CuotaAgotadaError
from bd import conectar_bd, guardar_unidad, guardar_recurso, guardar_introduccion
import costos

MAX_INTENTOS_REFORMULACION = 2

ASIGNATURA = os.getenv("ASIGNATURA", "Arquitectura y Organización de Computadores")
CODIGO = os.getenv("CODIGO_ASIGNATURA", "COMP_2010")

# Nombre del docente y logo institucional para la marca de agua del
# documento final (protección de autoría del material generado).
NOMBRE_DOCENTE = os.getenv("NOMBRE_DOCENTE", "Docente no especificado")
RUTA_LOGO_UTPL = os.getenv(
    "RUTA_LOGO_UTPL",
    os.path.join(os.path.dirname(__file__), "..", "assets", "logo_utpl.png")
)

# Identificador de trabajo usado solo para las corridas de consola (no
# aisladas por docente como en la web). Puede cambiarse por variable de
# entorno para llevar varias corridas de prueba en paralelo en la BD.
JOB_ID_CLI = os.getenv("JOB_ID_CLI", f"cli::{CODIGO}")


def _contexto_general(unidades: list[dict]) -> str:
    """El contexto general del curso es el mismo para todas las unidades
    (se arma una sola vez en base_conocimiento.construir_unidades), así
    que basta con tomarlo de la primera unidad que exista."""
    return unidades[0]["contexto_curso"] if unidades else ""


def ejecutar_pipeline(ruta_material: str, nombre_docente: str = None, marca_agua: bool = True):
    nombre_docente = nombre_docente or NOMBRE_DOCENTE
    job_id = JOB_ID_CLI
    costos.iniciar_registro()

    print("=" * 60)
    print("PASO 1 — Extractor de Texto")
    print("=" * 60)
    material = procesar_material_curso(ruta_material)

    print("\n" + "=" * 60)
    print("PASO 2 — Conexión a la base de datos")
    print("=" * 60)
    db = conectar_bd()
    if db is None:
        print("No se pudo conectar a MongoDB. Abortando pipeline.")
        return

    print("\n" + "=" * 60)
    print("PASO 3 — Base de Conocimiento (detección de unidades + clasificación)")
    print("=" * 60)
    unidades = construir_unidades(db, material, ASIGNATURA, CODIGO)
    resumen_cobertura(unidades)

    if not unidades:
        print("No se pudo determinar ninguna unidad para el curso. Abortando pipeline.")
        return

    for unidad in unidades:
        guardar_unidad(db, job_id, unidad)

    try:
        print("\n" + "=" * 60)
        print("PASO 3.5 — Introducción general del curso")
        print("=" * 60)
        introduccion = generar_introduccion_general(_contexto_general(unidades), ASIGNATURA, CODIGO)
        guardar_introduccion(db, job_id, introduccion)
        print("Introducción generada y guardada.")

        print("\n" + "=" * 60)
        print("PASO 4 — Generador de Recursos + Evaluador (1 llamada para generar, 1 para evaluar)")
        print("=" * 60)
        print("Nota: se genera documentación para TODAS las unidades, tengan o no material propio.")
        for unidad in unidades:
            recursos = generar_recursos_unidad(unidad)

            for tipo_recurso, contenido in recursos.items():
                guardar_recurso(db, job_id, unidad["numero"], tipo_recurso, contenido)

            reporte = evaluar_recursos_unidad(unidad, recursos)

            intentos = 0
            while reporte["necesita_reformular"] and intentos < MAX_INTENTOS_REFORMULACION:
                intentos += 1
                print(f"  Reformulando {reporte['necesita_reformular']} (intento {intentos})...")
                for tipo_recurso in reporte["necesita_reformular"]:
                    nuevo_contenido = GENERADORES_INDIVIDUALES[tipo_recurso](unidad)
                    guardar_recurso(db, job_id, unidad["numero"], tipo_recurso, nuevo_contenido)
                    recursos[tipo_recurso] = nuevo_contenido

                reporte = evaluar_recursos_unidad(unidad, recursos)

            if reporte["necesita_reformular"]:
                print(f"  [!] Unidad {unidad['numero']}: quedaron sin aprobar tras "
                      f"{MAX_INTENTOS_REFORMULACION} intentos: {reporte['necesita_reformular']}")
            else:
                print(f"  Unidad {unidad['numero']}: todos los recursos aprobados (puntaje >= 7).")

    except CuotaAgotadaError:
        print("\n" + "!" * 60)
        print("Se agotaron los créditos/tokens de la API de Gemini por ahora.")
        print("Lo ya generado quedó guardado en la base de datos (no se perdió nada).")
        print(f"Vuelve a correr este mismo comando más tarde (mismo JOB_ID_CLI='{job_id}') "
              f"para continuar exactamente donde se quedó.")
        print("!" * 60)
        costos.imprimir_resumen("Costos aproximados — corrida interrumpida por falta de cuota")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("PASO 5 — Exportador (documento Word final con marca de agua)")
    print("=" * 60)
    exportar_documento_final(
        db, job_id, unidades, ASIGNATURA, CODIGO,
        nombre_docente=nombre_docente,
        ruta_logo=RUTA_LOGO_UTPL if (marca_agua and os.path.isfile(RUTA_LOGO_UTPL)) else None,
    )

    costos.imprimir_resumen("Costos aproximados — ejecución completa")
    print("\nPipeline completo.")


if __name__ == "__main__":
    ruta_material = os.path.join(os.path.dirname(__file__), "..", "data", "material")
    ejecutar_pipeline(ruta_material)
