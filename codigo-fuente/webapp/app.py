"""
webapp/app.py — Interfaz web del Generador de Recursos Didácticos (UTPL)

Sin login: cualquiera que abra la página puede generar sus recursos
didácticos directamente, sin cuenta ni contraseña. El nombre del docente
se pide como un dato más del formulario "Nuevo documento" (se usa para
la portada y la marca de agua del Word final), no como credencial.

Pantallas:
  1. /                    — panel con los documentos generados (o pausados).
  2. /nuevo                — nombre del docente, carrera, ciclo académico,
                             periodo, asignatura y código.
  3. /subir/<job_id>       — dos apartados: (a) plan docente + guía
                             didáctica (opcional), (b) materiales extra.
  4. /marca_agua/<job_id>  — marca de agua institucional sí/no.
  5. /progreso/<job_id>    — avance en vivo, con barra de progreso y
                             botón para pausar manualmente.
  6. /vista_previa/<job_id> — recursos generados con su calificación,
                             y opción de marcar cuáles regenerar.

El pipeline real vive en ../src — esta app solo lo orquesta como
trabajos en segundo plano. La tabla de costos de cada corrida se
imprime en la consola donde corre `python app.py`, no en la web.
"""

import os
import sys
import threading

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_file, abort,
)

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.abspath(SRC_DIR))

import bd  # noqa: E402
from pipeline import ejecutar_pipeline_trabajo  # noqa: E402

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
MATERIAL_DIR = os.path.join(DATA_DIR, "material")
EXTENSIONES_PERMITIDAS = {".pdf", ".docx", ".pptx"}

# Los 4 tipos de recurso que existen por unidad, en el orden en que
# siempre se muestran (vista previa, checkboxes de regenerar, etc.)
TIPOS_RECURSO = ["resumen", "glosario", "preguntas", "actividad"]

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "utpl-generador-recursos-clave-de-desarrollo")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB por subida, holgado para varias diapositivas


def get_db():
    db = bd.conectar_bd()
    if db is None:
        abort(503, description="No se pudo conectar a la base de datos (MongoDB). Verifica que esté corriendo.")
    return db


def _trabajo_o_404(db, job_id):
    trabajo = bd.obtener_trabajo(db, job_id)
    if trabajo is None:
        abort(404)
    return trabajo


def _lanzar_pipeline_en_segundo_plano(job_id: str):
    def _tarea():
        db_hilo = bd.conectar_bd()
        if db_hilo is not None:
            ejecutar_pipeline_trabajo(db_hilo, job_id)
    hilo = threading.Thread(target=_tarea, daemon=True)
    hilo.start()


def _hay_otro_trabajo_activo(db, job_id):
    """Devuelve el trabajo que está en curso, si hay uno distinto al actual (regla de 'uno a la vez')."""
    return bd.obtener_trabajo_activo(db, excluir_job_id=job_id)


# ==========================================
# PANEL PRINCIPAL (documentos generados / en proceso)
# ==========================================

@app.route("/")
def dashboard():
    db = get_db()
    trabajos = bd.listar_trabajos(db)
    return render_template("dashboard.html", trabajos=trabajos)


# ==========================================
# PASO 1 — Datos generales del documento
# ==========================================

@app.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    if request.method == "POST":
        datos = {
            "nombre_docente": request.form.get("nombre_docente", "").strip(),
            "carrera": request.form.get("carrera", "").strip(),
            "ciclo_academico": request.form.get("ciclo_academico", "").strip(),
            "periodo": request.form.get("periodo", "").strip(),
            "asignatura": request.form.get("asignatura", "").strip(),
            "codigo": request.form.get("codigo", "").strip(),
        }
        if not datos["nombre_docente"] or not datos["asignatura"]:
            flash("El nombre del docente y la asignatura son obligatorios.", "error")
            return render_template("nuevo.html", datos=datos)

        db = get_db()
        job_id = bd.crear_trabajo(db, datos)
        return redirect(url_for("subir", job_id=job_id))

    datos_iniciales = {
        "nombre_docente": "", "carrera": "", "ciclo_academico": "",
        "periodo": "", "asignatura": "", "codigo": "",
    }
    return render_template("nuevo.html", datos=datos_iniciales)


# ==========================================
# PASO 2 — Subida de archivos (plan docente / guía y materiales extra)
# ==========================================

def _guardar_archivos(archivos, carpeta_destino, categoria):
    """Guarda los archivos en disco y devuelve la lista con su nombre y categoría, para dejarla en Mongo."""
    guardados = []
    os.makedirs(carpeta_destino, exist_ok=True)
    for archivo in archivos:
        if not archivo or not archivo.filename:
            continue
        extension = os.path.splitext(archivo.filename)[1].lower()
        if extension not in EXTENSIONES_PERMITIDAS:
            continue
        nombre_seguro = os.path.basename(archivo.filename)
        ruta_completa = os.path.join(carpeta_destino, nombre_seguro)
        archivo.save(ruta_completa)
        guardados.append({"nombre": nombre_seguro, "categoria": categoria})
    return guardados


@app.route("/subir/<job_id>", methods=["GET", "POST"])
def subir(job_id):
    db = get_db()
    trabajo = _trabajo_o_404(db, job_id)

    if request.method == "POST":
        carpeta_material = os.path.join(MATERIAL_DIR, job_id)

        guardados_plan = _guardar_archivos(request.files.getlist("plan_docente"), carpeta_material, "plan_docente")
        guardados_guia = _guardar_archivos(request.files.getlist("guia_didactica"), carpeta_material, "guia_didactica")
        guardados_extra = _guardar_archivos(request.files.getlist("materiales_extra"), carpeta_material, "material_extra")

        todos = guardados_plan + guardados_guia + guardados_extra
        if not todos:
            flash(
                "Sube al menos un archivo (idealmente el plan docente). Si no subes ningún plan docente, "
                "la estructura de unidades se detecta automáticamente a partir del resto del material.",
                "error",
            )
            return render_template("subir.html", trabajo=trabajo)

        bd.guardar_archivos_subidos(db, job_id, todos)
        bd.registrar_evento(db, job_id, "archivos_subidos", f"{len(todos)} archivo(s)")
        bd.actualizar_trabajo(db, job_id, {
            "ruta_material": carpeta_material,
            "mensaje": f"{len(todos)} archivo(s) subido(s). Falta confirmar la marca de agua.",
        })
        return redirect(url_for("marca_agua", job_id=job_id))

    return render_template("subir.html", trabajo=trabajo)


# ==========================================
# PASO 3 — Marca de agua sí/no, y disparo del pipeline
# ==========================================

@app.route("/marca_agua/<job_id>", methods=["GET", "POST"])
def marca_agua(job_id):
    db = get_db()
    trabajo = _trabajo_o_404(db, job_id)

    if not trabajo.get("ruta_material"):
        flash("Primero sube los archivos del curso.", "error")
        return redirect(url_for("subir", job_id=job_id))

    if request.method == "POST":
        trabajo_activo = _hay_otro_trabajo_activo(db, job_id)
        if trabajo_activo is not None:
            flash(
                f"Solo se puede generar un documento a la vez (todos comparten la misma cuota de la IA). "
                f"Ahora mismo se está generando \"{trabajo_activo.get('asignatura') or 'otro documento'}\". "
                f"Intenta de nuevo cuando termine.",
                "info",
            )
            return redirect(url_for("dashboard"))

        quiere_marca_agua = request.form.get("marca_agua") == "si"
        bd.actualizar_trabajo(db, job_id, {
            "marca_agua": quiere_marca_agua,
            "estado": "pendiente",
            "mensaje": "En cola para procesarse...",
        })
        bd.registrar_evento(db, job_id, "iniciado", "con marca de agua" if quiere_marca_agua else "sin marca de agua")
        _lanzar_pipeline_en_segundo_plano(job_id)
        return redirect(url_for("progreso", job_id=job_id))

    return render_template("marca_agua.html", trabajo=trabajo)


# ==========================================
# PASO 4 — Progreso en vivo + pausar/reanudar
# ==========================================

@app.route("/progreso/<job_id>")
def progreso(job_id):
    db = get_db()
    trabajo = _trabajo_o_404(db, job_id)
    return render_template("progreso.html", trabajo=trabajo)


@app.route("/api/estado/<job_id>")
def api_estado(job_id):
    db = get_db()
    trabajo = _trabajo_o_404(db, job_id)
    return jsonify({
        "estado": trabajo.get("estado"),
        "fase_actual": trabajo.get("fase_actual"),
        "unidad_actual": trabajo.get("unidad_actual"),
        "total_unidades": trabajo.get("total_unidades"),
        "progreso_pct": trabajo.get("progreso_pct") or 0,
        "mensaje": trabajo.get("mensaje"),
        "tiene_salida": bool(trabajo.get("ruta_salida")),
    })


@app.route("/pausar/<job_id>", methods=["POST"])
def pausar(job_id):
    """
    Marca que el docente pidió pausar. El pipeline revisa esta bandera
    justo antes de empezar cada unidad nueva y se detiene ahí (nunca a
    mitad de una llamada a la IA), así que puede tardar un poquito en
    hacer efecto si ya está a media unidad.
    """
    db = get_db()
    trabajo = _trabajo_o_404(db, job_id)
    if trabajo.get("estado") in ("procesando", "pendiente"):
        bd.actualizar_trabajo(db, job_id, {"pausar_solicitado": True})
        flash("Se pausará apenas termine la unidad que está generando ahora.", "info")
    return redirect(url_for("progreso", job_id=job_id))


@app.route("/continuar/<job_id>", methods=["POST"])
def continuar(job_id):
    db = get_db()
    trabajo = _trabajo_o_404(db, job_id)
    if trabajo.get("estado") in ("pausado_sin_creditos", "pausado_manual", "error"):
        trabajo_activo = _hay_otro_trabajo_activo(db, job_id)
        if trabajo_activo is not None:
            flash(
                f"Solo se puede procesar un documento a la vez. Ahora mismo se está generando "
                f"\"{trabajo_activo.get('asignatura') or 'otro documento'}\". Intenta continuar este cuando termine.",
                "info",
            )
            return redirect(url_for("progreso", job_id=job_id))

        bd.actualizar_trabajo(db, job_id, {
            "estado": "pendiente",
            "pausar_solicitado": False,
            "mensaje": "Reanudando la generación desde donde se quedó...",
        })
        bd.registrar_evento(db, job_id, "reanudado")
        _lanzar_pipeline_en_segundo_plano(job_id)
    return redirect(url_for("progreso", job_id=job_id))


@app.route("/descargar/<job_id>")
def descargar(job_id):
    db = get_db()
    trabajo = _trabajo_o_404(db, job_id)
    ruta_salida = trabajo.get("ruta_salida")
    if not ruta_salida or not os.path.isfile(ruta_salida):
        abort(404)
    nombre_descarga = f"{trabajo.get('codigo') or 'documento'}_recursos_didacticos.docx"
    return send_file(ruta_salida, as_attachment=True, download_name=nombre_descarga)


# ==========================================
# PASO 5 — Vista previa con calificaciones y regeneración manual
# ==========================================

@app.route("/vista_previa/<job_id>", methods=["GET", "POST"])
def vista_previa(job_id):
    db = get_db()
    trabajo = _trabajo_o_404(db, job_id)

    if request.method == "POST":
        seleccionados = request.form.getlist("recurso")  # llegan como "3:glosario", "1:resumen", etc.
        if not seleccionados:
            flash("No marcaste ningún apartado para regenerar.", "error")
            return redirect(url_for("vista_previa", job_id=job_id))

        trabajo_activo = _hay_otro_trabajo_activo(db, job_id)
        if trabajo_activo is not None:
            flash(
                f"Solo se puede procesar un documento a la vez. Ahora mismo se está generando "
                f"\"{trabajo_activo.get('asignatura') or 'otro documento'}\". Intenta de nuevo cuando termine.",
                "info",
            )
            return redirect(url_for("vista_previa", job_id=job_id))

        pendientes = []
        for item in seleccionados:
            numero_texto, tipo = item.split(":", 1)
            pendientes.append({"numero_unidad": int(numero_texto), "tipo_recurso": tipo})

        bd.actualizar_trabajo(db, job_id, {
            "regenerar_pendientes": pendientes,
            "estado": "pendiente",
            "mensaje": "En cola para regenerar los apartados marcados...",
        })
        _lanzar_pipeline_en_segundo_plano(job_id)
        return redirect(url_for("progreso", job_id=job_id))

    unidades = bd.obtener_unidades_trabajo(db, job_id)
    evaluaciones = bd.obtener_evaluaciones_trabajo(db, job_id)

    tabla_unidades = []
    for unidad in unidades:
        recursos = bd.obtener_recursos_unidad(db, job_id, unidad["numero"])
        reporte = evaluaciones.get(unidad["numero"], {}).get("detalle", {})
        apartados = []
        for tipo in TIPOS_RECURSO:
            apartados.append({
                "tipo": tipo,
                "contenido": recursos.get(tipo),
                "calificacion": reporte.get(tipo),
            })
        tabla_unidades.append({"numero": unidad["numero"], "titulo": unidad["titulo"], "apartados": apartados})

    return render_template("vista_previa.html", trabajo=trabajo, unidades=tabla_unidades)


def _retomar_trabajos_huerfanos():
    """
    Al arrancar el servidor, cualquier trabajo que haya quedado marcado
    'procesando' o 'pendiente' de una corrida anterior (por ejemplo, si el
    servidor se detuvo o se reinició a media generación) ya no tiene un
    hilo real trabajando en él. Sin esto, su pantalla de progreso se
    quedaría consultando el estado para siempre, sin avanzar ni avisar
    nada.

    Solo se procesa un documento a la vez, así que si hay varios
    huérfanos: el más antiguo se retoma de inmediato, y el resto queda
    en cola con su botón "Continuar procesando" listo.
    """
    db = bd.conectar_bd()
    if db is None:
        return
    huerfanos = bd.listar_trabajos_huerfanos(db)
    if not huerfanos:
        return

    primero, resto = huerfanos[0], huerfanos[1:]

    job_id = str(primero["_id"])
    print(f"  Retomando trabajo huérfano {job_id} ({primero.get('asignatura')})...")
    bd.actualizar_trabajo(db, job_id, {
        "estado": "pendiente",
        "mensaje": "El servidor se reinició durante la generación; retomando desde donde se quedó...",
    })
    _lanzar_pipeline_en_segundo_plano(job_id)

    for trabajo in resto:
        otro_job_id = str(trabajo["_id"])
        print(f"  Trabajo {otro_job_id} ({trabajo.get('asignatura')}) queda en cola "
              f"(solo se procesa un documento a la vez).")
        bd.actualizar_trabajo(db, otro_job_id, {
            "estado": "pausado_sin_creditos",
            "mensaje": (
                "El servidor se reinició mientras este documento se generaba. Además, solo se procesa "
                "un documento a la vez: presiona \"Continuar procesando\" cuando el otro termine."
            ),
        })


if __name__ == "__main__":
    os.makedirs(MATERIAL_DIR, exist_ok=True)
    # con el reloader de debug este archivo corre dos veces (proceso padre
    # y proceso hijo); WERKZEUG_RUN_MAIN solo está presente en el hijo real,
    # para no relanzar cada trabajo huérfano dos veces.
    debug_activo = os.getenv("FLASK_DEBUG", "0") == "1"
    if not debug_activo or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        _retomar_trabajos_huerfanos()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=debug_activo)
