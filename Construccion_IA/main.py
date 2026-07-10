"""
main.py — Orquestador principal

Ejecuta el pipeline completo siguiendo el flujo de tu diagrama C4:

  extractor -> base_conocimiento -> bd (guarda unidades) -> introducción general
  -> generador_recursos -> bd (guarda recursos) -> evaluador (reformula si <7)
  -> exportador -> docx final
"""

import os
from extractor import procesar_material_curso
from base_conocimiento import construir_unidades, resumen_cobertura
from generador_recursos import generar_todos_los_recursos, generar_resumen_ejecutivo, \
    generar_glosario, generar_preguntas_comprension, generar_actividad_reflexion, \
    generar_introduccion_general
from evaluador import evaluar_unidad_completa
from exportador import exportar_documento_final
from bd import conectar_bd, guardar_unidad, guardar_recurso, guardar_introduccion

# Regenera un recurso puntual usando su función específica
FUNCIONES_REGENERACION = {
    "resumen": generar_resumen_ejecutivo,
    "glosario": generar_glosario,
    "preguntas": generar_preguntas_comprension,
    "actividad": generar_actividad_reflexion,
}

MAX_INTENTOS_REFORMULACION = 2

ASIGNATURA = os.getenv("ASIGNATURA", "Arquitectura y Organización de Computadores")
CODIGO = os.getenv("CODIGO_ASIGNATURA", "COMP_2010")


def ejecutar_pipeline(ruta_material: str):
    print("=" * 60)
    print("PASO 1 — Extractor de Texto")
    print("=" * 60)
    material = procesar_material_curso(ruta_material)

    print("\n" + "=" * 60)
    print("PASO 2 — Base de Conocimiento")
    print("=" * 60)
    unidades = construir_unidades(material, ASIGNATURA, CODIGO)
    resumen_cobertura(unidades)

    print("\n" + "=" * 60)
    print("PASO 3 — Conexión a la base de datos")
    print("=" * 60)
    db = conectar_bd()
    if db is None:
        print("No se pudo conectar a MongoDB. Abortando pipeline.")
        return

    for unidad in unidades:
        guardar_unidad(db, unidad)

    print("\n" + "=" * 60)
    print("PASO 3.5 — Introducción general del curso")
    print("=" * 60)
    introduccion = generar_introduccion_general(material["material_general"], ASIGNATURA, CODIGO)
    guardar_introduccion(db, introduccion)
    print("Introducción generada y guardada.")

    print("\n" + "=" * 60)
    print("PASO 4 — Generador de Recursos + Evaluador")
    print("=" * 60)
    for unidad in unidades:
        if not unidad["tiene_material"]:
            continue

        recursos = generar_todos_los_recursos(unidad)
        if not recursos:
            continue

        for tipo_recurso, contenido in recursos.items():
            guardar_recurso(db, unidad["numero"], tipo_recurso, contenido)

        print(f"  Evaluando recursos de la Unidad {unidad['numero']}...")
        reporte = evaluar_unidad_completa(unidad, recursos)

        intentos = 0
        while reporte["necesita_reformular"] and intentos < MAX_INTENTOS_REFORMULACION:
            intentos += 1
            print(f"  Reformulando {reporte['necesita_reformular']} (intento {intentos})...")
            for tipo_recurso in reporte["necesita_reformular"]:
                nuevo_contenido = FUNCIONES_REGENERACION[tipo_recurso](unidad)
                guardar_recurso(db, unidad["numero"], tipo_recurso, nuevo_contenido)
                recursos[tipo_recurso] = nuevo_contenido

            reporte = evaluar_unidad_completa(unidad, recursos)

        if reporte["necesita_reformular"]:
            print(f"  [!] Unidad {unidad['numero']}: quedaron sin aprobar tras "
                  f"{MAX_INTENTOS_REFORMULACION} intentos: {reporte['necesita_reformular']}")
        else:
            print(f"  Unidad {unidad['numero']}: todos los recursos aprobados (puntaje >= 7).")

    print("\n" + "=" * 60)
    print("PASO 5 — Exportador (documento Word final)")
    print("=" * 60)
    exportar_documento_final(unidades, ASIGNATURA, CODIGO)

    print("\nPipeline completo.")


if __name__ == "__main__":
    ruta_material = os.path.join(os.path.dirname(__file__), "..", "data", "material")
    ejecutar_pipeline(ruta_material)
