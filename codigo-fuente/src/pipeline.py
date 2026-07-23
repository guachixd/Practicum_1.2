"""
pipeline.py — Orquestador resumible para la interfaz web

Corre el flujo completo (extractor -> base_conocimiento -> generador de
recursos -> evaluador -> exportador) pensado para que un docente lo use
desde el navegador sin saber nada de esto por dentro:

1. Todo queda aislado por trabajo (job_id) en MongoDB, para que se
   puedan generar varios documentos sin pisarse datos entre sí.

2. Es RESUMIBLE. Si Gemini se queda sin cuota a media generación, el
   trabajo se marca "pausado_sin_creditos" y la función simplemente
   retorna, sin reventar el proceso. Al volver a llamar a
   ejecutar_pipeline_trabajo() con el mismo job_id, se detecta qué ya
   está guardado y solo se genera lo que falta.

3. Por unidad se hacen solo 2 llamadas a Gemini (una para generar los 4
   recursos juntos, otra para evaluarlos juntos), en vez de 8. Si el
   docente pausa manualmente, el corte pasa justo antes de empezar la
   siguiente unidad, nunca a mitad de una llamada a la IA.

4. Si el trabajo trae "regenerar_pendientes" (el docente pidió rehacer
   uno o varios apartados puntuales desde la vista previa), el pipeline
   solo rehace esos, no toda la unidad.
"""

import os

from extractor import procesar_material_curso
from base_conocimiento import construir_unidades, resumen_cobertura
from generador_recursos import (
    generar_recursos_unidad, generar_introduccion_general, GENERADORES_INDIVIDUALES,
)
from evaluador import evaluar_recursos_unidad, evaluar_recurso
from exportador import exportar_documento_final
from reintentos import CuotaAgotadaError
import bd
import costos

MAX_INTENTOS_REFORMULACION = 2

RUTA_LOGO_UTPL_DEFECTO = os.path.join(os.path.dirname(__file__), "..", "assets", "logo_utpl.png")

MENSAJE_SIN_CREDITOS = (
    "Se agotaron los créditos/tokens disponibles de la IA en este momento. "
    "Tu progreso quedó guardado tal como iba: nada de lo ya generado se "
    "pierde. Cuando quieras, presiona \"Continuar procesando\" para "
    "retomar la generación exactamente desde donde se quedó."
)
MENSAJE_PAUSADO_MANUAL = (
    "Pausaste la generación tú mismo. Todo lo generado hasta ahora quedó "
    "guardado. Presiona \"Continuar procesando\" cuando quieras seguir."
)


def _marcar(db, job_id: str, **campos):
    bd.actualizar_trabajo(db, job_id, campos)


def _debe_pausarse(db, job_id: str) -> bool:
    """
    Revisa si alguien apretó el botón de pausa mientras el pipeline
    estaba trabajando (se guarda en un campo aparte porque el botón se
    aprieta desde otra petición web, en otro momento). Se mira justo
    antes de arrancar cada unidad nueva, nunca a mitad de una llamada a
    la IA.
    """
    trabajo = bd.obtener_trabajo(db, job_id)
    return bool(trabajo and trabajo.get("pausar_solicitado"))


def _actualizar_progreso(db, job_id: str, numero_unidad_actual: int, total_unidades: int, mensaje: str):
    porcentaje = round(100 * (numero_unidad_actual - 1) / total_unidades) if total_unidades else 0
    _marcar(db, job_id, fase_actual="generacion", unidad_actual=numero_unidad_actual,
            total_unidades=total_unidades, progreso_pct=porcentaje, mensaje=mensaje)


def _guardar_costos_y_calificaciones(db, job_id: str, unidades: list[dict]) -> None:
    """
    Junta el costo real de esta corrida (ver costos.py) y un resumen de
    cuántos recursos se aprobaron a la primera vs. cuántos necesitaron
    reformular, y lo deja guardado con el trabajo. Antes esto solo se
    veía en la consola y se perdía al cerrarla.
    """
    datos_costo = costos.resumen_datos()

    aprobados_primera = 0
    reformulados = 0
    for unidad in unidades:
        reporte = bd.obtener_evaluacion_unidad(db, job_id, unidad["numero"])
        if not reporte:
            continue
        for calificacion in reporte["detalle"].values():
            if calificacion.get("aprobado"):
                aprobados_primera += 1
            else:
                reformulados += 1

    resumen_calificaciones = {
        "aprobados_primera": aprobados_primera,
        "reformulados": reformulados,
    }

    bd.guardar_resultado_costos(db, job_id, datos_costo["costo_total_usd"], resumen_calificaciones)


def _generar_y_evaluar_unidad(db, job_id: str, unidad: dict) -> None:
    """
    Hace todo el trabajo de una unidad: genera lo que falte, evalúa, y
    reformula lo que no apruebe (hasta MAX_INTENTOS_REFORMULACION veces).
    Al final deja guardado en Mongo tanto los recursos como el reporte
    de evaluación.
    """
    numero = unidad["numero"]
    recursos = bd.obtener_recursos_unidad(db, job_id, numero)
    faltan_todos = not recursos

    if faltan_todos:
        recursos = generar_recursos_unidad(unidad)
        for tipo, contenido in recursos.items():
            bd.guardar_recurso(db, job_id, numero, tipo, contenido)
    else:
        # puede pasar si el trabajo se pausó justo después de generar pero
        # antes de evaluar; no hace falta pedirle a Gemini que regenere nada
        faltantes = [t for t in GENERADORES_INDIVIDUALES if t not in recursos]
        for tipo in faltantes:
            contenido = GENERADORES_INDIVIDUALES[tipo](unidad)
            bd.guardar_recurso(db, job_id, numero, tipo, contenido)
            recursos[tipo] = contenido

    if bd.obtener_evaluacion_unidad(db, job_id, numero) is not None:
        return

    reporte = evaluar_recursos_unidad(unidad, recursos)

    intentos = 0
    while reporte["necesita_reformular"] and intentos < MAX_INTENTOS_REFORMULACION:
        intentos += 1
        print(f"  Reformulando {reporte['necesita_reformular']} de la Unidad {numero} (intento {intentos})...")
        for tipo in reporte["necesita_reformular"]:
            nuevo_contenido = GENERADORES_INDIVIDUALES[tipo](unidad)
            bd.guardar_recurso(db, job_id, numero, tipo, nuevo_contenido)
            recursos[tipo] = nuevo_contenido
        reporte = evaluar_recursos_unidad(unidad, recursos)

    bd.guardar_evaluacion_unidad(db, job_id, numero, reporte)


def _regenerar_apartados_pedidos(db, job_id: str, unidades: list[dict], pendientes: list[dict]) -> None:
    """
    Regenera solo los apartados puntuales que el docente marcó en la
    vista previa (ej. el glosario de la Unidad 2 y el resumen de la
    Unidad 4), sin tocar el resto del documento. Guarda la versión
    anterior de cada uno antes de reemplazarla.
    """
    unidades_por_numero = {u["numero"]: u for u in unidades}

    for pedido in pendientes:
        numero = pedido["numero_unidad"]
        tipo = pedido["tipo_recurso"]
        unidad = unidades_por_numero.get(numero)
        if unidad is None:
            continue

        _marcar(db, job_id, mensaje=f"Regenerando {tipo} de la Unidad {numero} (pedido manualmente)...")

        recursos_actuales = bd.obtener_recursos_unidad(db, job_id, numero)
        version_anterior = recursos_actuales.get(tipo)
        if version_anterior is not None:
            bd.guardar_version_anterior_recurso(db, job_id, numero, tipo, version_anterior)

        nuevo_contenido = GENERADORES_INDIVIDUALES[tipo](unidad)
        bd.guardar_recurso(db, job_id, numero, tipo, nuevo_contenido)

        nueva_calificacion = evaluar_recurso(tipo, nuevo_contenido, unidad["contenido"], unidad["tiene_material"])
        bd.actualizar_calificacion_recurso(db, job_id, numero, tipo, nueva_calificacion)
        print(f"  {tipo} de la Unidad {numero} regenerado a pedido del docente: "
              f"{nueva_calificacion.get('puntaje', 0)}/10")

    bd.actualizar_trabajo(db, job_id, {"regenerar_pendientes": []})
    bd.registrar_evento(db, job_id, "regenerado_manual",
                         ", ".join(f"Unidad {p['numero_unidad']} · {p['tipo_recurso']}" for p in pendientes))


def ejecutar_pipeline_trabajo(db, job_id: str) -> None:
    """
    Ejecuta (o retoma) la generación de recursos didácticos de un trabajo.
    Pensada para correr en un hilo en segundo plano desde la app web,
    mientras el docente ve la pantalla de progreso.
    """
    trabajo = bd.obtener_trabajo(db, job_id)
    if trabajo is None:
        return

    asignatura_fallback = trabajo.get("asignatura") or "Asignatura no especificada"
    codigo_fallback = trabajo.get("codigo") or "SIN_CODIGO"
    nombre_docente = trabajo.get("nombre_docente") or "Docente no especificado"

    costos.iniciar_registro()

    _marcar(db, job_id, estado="procesando", fase_actual="extraccion",
            unidad_actual=None, mensaje="Leyendo los archivos subidos del curso...")

    try:
        unidades = bd.obtener_unidades_trabajo(db, job_id)

        if not unidades:
            material = procesar_material_curso(trabajo["ruta_material"])
            unidades = construir_unidades(db, material, asignatura_fallback, codigo_fallback)
            resumen_cobertura(unidades)

            if not unidades:
                _marcar(db, job_id, estado="error",
                        mensaje="No se pudo determinar ninguna unidad a partir del material subido. "
                                "Revisa que el plan docente esté entre los archivos.")
                return

            for unidad in unidades:
                bd.guardar_unidad(db, job_id, unidad)

        total_unidades = len(unidades)
        _marcar(db, job_id, total_unidades=total_unidades)

        # Si el docente pidió regenerar algo puntual desde la vista previa,
        # el documento ya estaba completo antes: solo hay que rehacer esos
        # apartados y volver a exportar, no correr todo el pipeline de nuevo.
        pendientes = trabajo.get("regenerar_pendientes") or []
        if pendientes:
            _marcar(db, job_id, mensaje="Regenerando los apartados pedidos...")
            _regenerar_apartados_pedidos(db, job_id, unidades, pendientes)
        else:
            contexto_general = unidades[0]["contexto_curso"] if unidades else ""

            introduccion = bd.obtener_introduccion(db, job_id)
            if not introduccion:
                _marcar(db, job_id, fase_actual="introduccion",
                        mensaje="Generando la introducción general del curso...")
                introduccion = generar_introduccion_general(contexto_general, asignatura_fallback, codigo_fallback)
                bd.guardar_introduccion(db, job_id, introduccion)

            for unidad in unidades:
                if _debe_pausarse(db, job_id):
                    _marcar(db, job_id, estado="pausado_manual", pausar_solicitado=False,
                            mensaje=MENSAJE_PAUSADO_MANUAL)
                    bd.registrar_evento(db, job_id, "pausado_manual", f"Antes de la Unidad {unidad['numero']}")
                    _guardar_costos_y_calificaciones(db, job_id, unidades)
                    costos.imprimir_resumen(f"Costos aproximados — {asignatura_fallback} — PAUSADO MANUALMENTE")
                    return

                _actualizar_progreso(db, job_id, unidad["numero"], total_unidades,
                                      f"Generando recursos de la Unidad {unidad['numero']}: {unidad['titulo']}...")
                _generar_y_evaluar_unidad(db, job_id, unidad)

        _marcar(db, job_id, fase_actual="exportacion", unidad_actual=None, progreso_pct=100,
                mensaje="Generando el documento Word final...")

        ruta_logo = None
        if trabajo.get("marca_agua", True):
            ruta_logo = trabajo.get("ruta_logo") or RUTA_LOGO_UTPL_DEFECTO
            if not os.path.isfile(ruta_logo):
                ruta_logo = None

        ruta_salida = exportar_documento_final(
            db, job_id, unidades, asignatura_fallback, codigo_fallback,
            nombre_docente=nombre_docente,
            ruta_logo=ruta_logo,
            ruta_salida=trabajo.get("ruta_salida"),
            carrera=trabajo.get("carrera") or "",
            ciclo_academico=trabajo.get("ciclo_academico") or "",
            periodo=trabajo.get("periodo") or "",
        )

        _guardar_costos_y_calificaciones(db, job_id, unidades)
        _marcar(db, job_id, estado="completado", fase_actual="finalizado", unidad_actual=None,
                mensaje="Documento generado correctamente.", ruta_salida=ruta_salida)
        bd.registrar_evento(db, job_id, "completado")
        costos.imprimir_resumen(f"Costos aproximados — {asignatura_fallback} — COMPLETADO")

    except CuotaAgotadaError:
        _marcar(db, job_id, estado="pausado_sin_creditos", mensaje=MENSAJE_SIN_CREDITOS)
        bd.registrar_evento(db, job_id, "pausado_sin_creditos")
        _guardar_costos_y_calificaciones(db, job_id, bd.obtener_unidades_trabajo(db, job_id))
        costos.imprimir_resumen(f"Costos aproximados — {asignatura_fallback} — PAUSADO SIN CUOTA")

    except Exception as e:
        _marcar(db, job_id, estado="error", mensaje=f"Ocurrió un error inesperado: {e}")
        bd.registrar_evento(db, job_id, "error", str(e))
        costos.imprimir_resumen(f"Costos aproximados — {asignatura_fallback} — ERROR")
