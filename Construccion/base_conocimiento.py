"""
base_conocimiento.py
---------------------
Construye el diccionario de la base de conocimiento a partir del texto
ya extraído por extractor.py.

Estructura de salida (la misma que pide el reto):

    base = {
        'asignatura': '...',
        'codigo': '...',
        'carrera': '...',
        'ciclo': '...',
        'unidades': [
            {
                'numero': 1,
                'titulo': '...',
                'objetivos': '...',
                'contenido': '...',
                'actividades': '...',
            },
            ...
        ]
    }

La asignatura usada como ejemplo real es "Arquitectura y Organización
de Computadores" (COMP_2010), 4to ciclo de Computación - UTPL, tal como
aparece en data/plan_docente.pdf.
"""

from __future__ import annotations

import re
from pathlib import Path

from extractor import extraer_texto_pdf, extraer_carpeta_materiales

# Datos fijos de la asignatura (según el plan docente real, sección A).
ASIGNATURA = "Arquitectura y Organización de Computadores"
CODIGO = "COMP_2010"
CARRERA = "Computación"
CICLO = "4to"

# Las 4 unidades del reto, agrupadas por rango de semanas del plan
# docente (mismo agrupamiento que el diagrama de arquitectura entregado
# en la semana 1).
UNIDADES_DEF = [
    {
        "numero": 1,
        "titulo": "Von Neumann, generaciones e interconexiones",
        "semanas": range(1, 4),  # semanas 1-3
        "materiales": ["semana1"],
    },
    {
        "numero": 2,
        "titulo": "Memoria, caché, E/S e interconexiones",
        "semanas": range(4, 8),  # semanas 4-7
        "materiales": ["semana3"],
    },
    {
        "numero": 3,
        "titulo": "ALU, repertorio de instrucciones y ciclo de instrucción",
        "semanas": range(9, 12),  # semanas 9-11
        "materiales": [],
    },
    {
        "numero": 4,
        "titulo": "RISC/CISC y procesamiento paralelo (VHDL)",
        "semanas": range(12, 15),  # semanas 12-14
        "materiales": [],
    },
]

# El plan docente extraído con pypdf trae el texto de cada "Semana N"
# en un bloque desordenado por la forma en que PyPDF lee las tablas del
# PDF (por ejemplo "emana 1S" en vez de "Semana 1"). Este patrón es
# consistente en todo el documento, así que sirve como separador
# confiable de bloques por semana.
PATRON_SEMANA = re.compile(r"emana\s+(\d{1,2})\s*S?\b")


def segmentar_por_semana(texto_plan: str) -> dict[int, str]:
    """
    Divide el texto completo del plan docente en bloques por semana,
    usando las apariciones de "Semana N" como marcadores.

    Devuelve {numero_semana: texto_del_bloque}.
    """
    coincidencias = list(PATRON_SEMANA.finditer(texto_plan))
    bloques: dict[int, str] = {}

    for i, m in enumerate(coincidencias):
        numero_semana = int(m.group(1))
        inicio = m.end()
        fin = coincidencias[i + 1].start() if i + 1 < len(coincidencias) else len(texto_plan)
        bloque = texto_plan[inicio:fin].strip()

        # Si la misma semana aparece más de una vez (p. ej. referenciada
        # en el cronograma de evaluaciones al final del documento), nos
        # quedamos con el bloque más largo, que es el que trae el
        # contenido real de la planificación semanal.
        if numero_semana not in bloques or len(bloque) > len(bloques[numero_semana]):
            bloques[numero_semana] = bloque

    return bloques


def _extraer_seccion(bloque: str, inicio_marcador: str, fin_marcadores: list[str]) -> str:
    """
    Utilidad simple para recortar, dentro del bloque de una semana, el
    texto entre un marcador de inicio y el primero de varios posibles
    marcadores de fin. Si no encuentra el marcador de inicio, devuelve
    una cadena vacía en lugar de inventar contenido.
    """
    idx_inicio = bloque.find(inicio_marcador)
    if idx_inicio == -1:
        return ""
    idx_inicio += len(inicio_marcador)

    idx_fin = len(bloque)
    for marcador in fin_marcadores:
        idx = bloque.find(marcador, idx_inicio)
        if idx != -1:
            idx_fin = min(idx_fin, idx)

    return bloque[idx_inicio:idx_fin].strip()


def construir_base_conocimiento(ruta_plan_docente: str, ruta_carpeta_materiales: str) -> dict:
    """
    Orquesta la extracción y segmentación para producir el diccionario
    final de la base de conocimiento.
    """
    texto_plan = extraer_texto_pdf(ruta_plan_docente)
    bloques_semana = segmentar_por_semana(texto_plan)

    materiales_extraidos = extraer_carpeta_materiales(ruta_carpeta_materiales)

    unidades = []
    for definicion in UNIDADES_DEF:
        objetivos_semanas = []
        contenido_semanas = []
        actividades_semanas = []

        for num_semana in definicion["semanas"]:
            bloque = bloques_semana.get(num_semana)
            if not bloque:
                continue

            objetivos = _extraer_seccion(
                bloque, "aprendizaje de la\nasignatura", ["ontenidos a"]
            )
            contenido = _extraer_seccion(
                bloque, "desarrollarse", ["ctividades del"]
            )
            actividades = _extraer_seccion(
                bloque, "Aprendizaje en\ncontacto con el\ndocente",
                ["o r a s  d e l", "ctividades del"],
            )

            if objetivos:
                objetivos_semanas.append(f"Semana {num_semana}: {objetivos}")
            if contenido:
                contenido_semanas.append(f"Semana {num_semana}: {contenido}")
            if actividades:
                actividades_semanas.append(f"Semana {num_semana}: {actividades}")

        # Se agrega el material de clase real (diapositivas) cuando
        # existe texto extraíble para esa unidad.
        for nombre_material in definicion["materiales"]:
            if nombre_material in materiales_extraidos:
                contenido_semanas.append(
                    f"\n--- Material de clase ({nombre_material}) ---\n"
                    + materiales_extraidos[nombre_material]
                )

        unidades.append(
            {
                "numero": definicion["numero"],
                "titulo": definicion["titulo"],
                "objetivos": "\n".join(objetivos_semanas).strip(),
                "contenido": "\n".join(contenido_semanas).strip(),
                "actividades": "\n".join(actividades_semanas).strip(),
            }
        )

    return {
        "asignatura": ASIGNATURA,
        "codigo": CODIGO,
        "carrera": CARRERA,
        "ciclo": CICLO,
        "unidades": unidades,
    }


if __name__ == "__main__":
    # Prueba rápida manual: python src/base_conocimiento.py
    base_dir = Path(__file__).resolve().parent.parent
    base = construir_base_conocimiento(
        str(base_dir / "data" / "plan_docente.pdf"),
        str(base_dir / "data" / "materiales"),
    )

    print(f"Asignatura: {base['asignatura']} ({base['codigo']})")
    for u in base["unidades"]:
        print(
            f"\nUnidad {u['numero']}: {u['titulo']}"
            f"\n  objetivos:   {len(u['objetivos'])} caracteres"
            f"\n  contenido:   {len(u['contenido'])} caracteres"
            f"\n  actividades: {len(u['actividades'])} caracteres"
        )
