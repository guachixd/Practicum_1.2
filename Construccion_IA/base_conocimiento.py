"""
base_conocimiento.py — Base de Conocimiento

Corresponde al contenedor "Base de Conocimiento" de tu diagrama C4.
Toma el material ya extraído (dict devuelto por extractor.procesar_material_curso)
y lo organiza en 8 unidades, combinando el material propio de cada unidad con
el contexto compartido del material general del curso (todo lo que estaba en
la raíz de data/material/, sin importar cómo se llamaban los archivos).
"""


def construir_unidades(material_extraido: dict, asignatura: str, codigo: str) -> list[dict]:
    """
    Construye la lista de 8 unidades listas para pasarle al Generador de Recursos.

    Cada unidad queda con:
      - numero, titulo, asignatura, codigo
      - contenido: el material propio de esa unidad (diapositivas, lecturas, etc.)
      - contexto_curso: el material general del curso (plan docente, guías, etc.,
        sin importar su nombre de archivo), usado como contexto compartido para
        que Gemini entienda el marco general de la asignatura.
    """
    contexto_curso = material_extraido.get("material_general", "")

    unidades = []
    for n in range(1, 9):
        contenido_unidad = material_extraido["unidades"].get(n, "")

        unidad = {
            "numero": n,
            "titulo": f"Unidad {n}",
            "asignatura": asignatura,
            "codigo": codigo,
            "contenido": contenido_unidad,
            "contexto_curso": contexto_curso,
            "tiene_material": bool(contenido_unidad.strip())
        }
        unidades.append(unidad)

    return unidades


def resumen_cobertura(unidades: list[dict]) -> None:
    """Imprime un resumen de qué unidades tienen material y cuáles no."""
    print("\n--- COBERTURA DE LA BASE DE CONOCIMIENTO ---")
    for u in unidades:
        estado = "OK" if u["tiene_material"] else "SIN MATERIAL"
        print(f"  Unidad {u['numero']}: {len(u['contenido'])} caracteres [{estado}]")


# ==========================================
# BLOQUE DE PRUEBA LOCAL
# ==========================================
if __name__ == "__main__":
    import os
    from extractor import procesar_material_curso

    ruta_material = os.path.join(os.path.dirname(__file__), "..", "data", "material")
    material = procesar_material_curso(ruta_material)

    unidades = construir_unidades(
        material,
        asignatura="Arquitectura y Organización de Computadores",
        codigo="COMP_2010"
    )

    resumen_cobertura(unidades)

    print("\n--- EJEMPLO: Unidad 1 completa ---")
    print(f"Título: {unidades[0]['titulo']}")
    print(f"Contenido:\n{unidades[0]['contenido']}")
    print(f"\nContexto del curso (primeros 200 caracteres):\n{unidades[0]['contexto_curso'][:200]}")
