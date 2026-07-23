"""
base_conocimiento.py — Base de Conocimiento

Corresponde al contenedor "Base de Conocimiento" de tu diagrama C4.
Toma los documentos ya extraídos (dict devuelto por
extractor.procesar_material_curso) y arma la lista de unidades del curso.

Cambio de fondo (v2):
- El número de unidades y sus títulos YA NO están fijos en 8: se detectan
  dinámicamente a partir del plan docente (clasificador.identificar_estructura_curso).
- Como ya no hay carpetas unidad_01/, unidad_02/..., cada archivo se
  asigna a su unidad por contenido (clasificador.clasificar_documento),
  no por convención de carpetas.
- Una unidad sin material propio (porque el docente no subió diapositivas
  de ese tema) YA NO se salta: queda con "contenido" vacío pero con
  "titulo" y "temas" (sacados del plan docente), que es información
  suficiente para que generador_recursos.py pueda igual producir toda su
  documentación. "tiene_material" queda solo como dato informativo, ya
  no como condición para generar o no.
"""

from clasificador import identificar_estructura_curso, clasificar_todos_los_documentos


def construir_unidades(db, material_extraido: dict, asignatura: str, codigo: str) -> list[dict]:
    """
    Construye la lista de unidades del curso, listas para pasarle al
    Generador de Recursos. `db` se usa para el caché de clasificación
    (ver clasificador.py) — puede ser None si se corre sin base de datos.

    Cada unidad queda con:
      - numero, titulo, temas, asignatura, codigo
      - contenido: texto combinado de los archivos clasificados en esa
        unidad (puede quedar vacío si el docente no subió material propio
        de esa unidad; igual se genera documentación a partir del título
        y los temas del plan docente).
      - contexto_curso: material general del curso (plan docente, guías,
        y cualquier archivo que no se pudo asociar a una unidad específica),
        usado como contexto compartido para todas las unidades.
      - tiene_material: informativo, indica si hubo archivos propios de
        esa unidad o no.
      - fuentes: nombres de los archivos que alimentaron el "contenido"
        de la unidad, para trazabilidad.
    """
    documentos = material_extraido.get("documentos", [])

    estructura = identificar_estructura_curso(db, documentos, asignatura, codigo)
    unidades_detectadas = estructura["unidades"]

    if estructura.get("inferido"):
        print("  [!] No se encontró un plan docente explícito; la estructura de unidades fue inferida del material.")
    else:
        fuente = estructura.get("fuente_detectada") or "desconocida"
        print(f"  Estructura de unidades detectada desde: {fuente}")

    clasificacion = clasificar_todos_los_documentos(db, documentos, unidades_detectadas)

    # Arma el contenido de cada unidad y el contexto general del curso a
    # partir de los archivos que el clasificador les asignó.
    contenido_por_unidad: dict[int, list[str]] = {u["numero"]: [] for u in unidades_detectadas}
    fuentes_por_unidad: dict[int, list[str]] = {u["numero"]: [] for u in unidades_detectadas}
    bloques_contexto_general = []

    for documento in documentos:
        if not documento.get("utilizable"):
            continue
        resultado = clasificacion.get(documento["nombre"], {"unidad": 0})
        numero_unidad = resultado["unidad"]
        bloque = f"--- {documento['nombre']} ---\n{documento['texto']}"

        if numero_unidad == 0 or numero_unidad not in contenido_por_unidad:
            bloques_contexto_general.append(bloque)
        else:
            contenido_por_unidad[numero_unidad].append(bloque)
            fuentes_por_unidad[numero_unidad].append(documento["nombre"])

    contexto_curso = "\n\n".join(bloques_contexto_general)

    unidades = []
    for u in unidades_detectadas:
        numero = u["numero"]
        contenido_unidad = "\n\n".join(contenido_por_unidad.get(numero, []))

        unidad = {
            "numero": numero,
            "titulo": u.get("titulo", f"Unidad {numero}"),
            "temas": u.get("temas", []),
            "asignatura": estructura.get("asignatura") or asignatura,
            "codigo": estructura.get("codigo") or codigo,
            "contenido": contenido_unidad,
            "contexto_curso": contexto_curso,
            "tiene_material": bool(contenido_unidad.strip()),
            "fuentes": fuentes_por_unidad.get(numero, []),
        }
        unidades.append(unidad)

    return unidades


def resumen_cobertura(unidades: list[dict]) -> None:
    """Imprime un resumen de qué unidades tienen material propio y cuáles se generarán solo desde el plan docente."""
    print("\n--- COBERTURA DE LA BASE DE CONOCIMIENTO ---")
    for u in unidades:
        if u["tiene_material"]:
            estado = f"OK ({len(u['fuentes'])} archivo(s): {', '.join(u['fuentes'])})"
        else:
            estado = "SIN MATERIAL PROPIO — se generará desde el plan docente"
        print(f"  Unidad {u['numero']} — {u['titulo']}: {len(u['contenido'])} caracteres [{estado}]")


# ==========================================
# BLOQUE DE PRUEBA LOCAL
# ==========================================
if __name__ == "__main__":
    import os
    from extractor import procesar_material_curso

    ruta_material = os.path.join(os.path.dirname(__file__), "..", "data", "material")
    material = procesar_material_curso(ruta_material)

    unidades = construir_unidades(
        None, material,
        asignatura="Arquitectura y Organización de Computadores",
        codigo="COMP_2010"
    )

    resumen_cobertura(unidades)
