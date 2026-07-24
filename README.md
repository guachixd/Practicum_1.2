# Práctica Preprofesional — Danny Guachisaca

**Universidad Técnica Particular de Loja (UTPL)**
Práctica Preprofesional 1.2 · Eje de Agentes de IA
Danny Sebastián Guachisaca Contento — Cuarto ciclo

## De qué trata este repositorio

Aquí está todo lo que hice durante estas 7 semanas de prácticas: el
código del proyecto, el estado del arte, el diagrama de arquitectura y
las presentaciones de avance.

Mi reto fue construir un **generador automático de recursos didácticos**
para los docentes de la UTPL: un sistema al que un docente le sube el
material de su asignatura (plan docente, diapositivas, lecturas) y le
devuelve, listo para descargar, un documento Word con resumen ejecutivo,
glosario, preguntas de comprensión y una actividad de reflexión por
cada unidad del curso — generado con IA (Google Gemini), pero revisado
automáticamente antes de entregarse.

## Qué construí

- Una **página web** (sin necesidad de cuenta ni contraseña) donde el
  docente sube su material, elige si quiere marca de agua institucional,
  y ve el progreso en vivo mientras se genera su documento.
- Un **pipeline** que detecta la estructura de unidades del curso a
  partir del plan docente (o la infiere si no hay uno reconocible),
  clasifica cada archivo subido en su unidad correspondiente, y genera
  los 4 recursos didácticos por unidad.
- Un **evaluador automático**: cada recurso generado se le pasa de
  vuelta a la IA para que lo puntúe de 0 a 10, y si no aprueba, se
  reformula solo antes de llegar al documento final.
- Una capa de **resiliencia** pensada para la cuota gratuita de la API:
  reintentos con espera, un pipeline que se puede pausar y retomar sin
  perder lo ya generado, recuperación automática si el servidor se
  reinicia a medio proceso, y una tabla de costos reales impresa en
  consola al terminar cada corrida.
- Una vista donde el docente puede revisar la calificación de cada
  apartado generado y pedir que se regenere solo el que no le convenció,
  sin tener que rehacer todo el documento.

## Estructura del repositorio

codigo-fuente/ El proyecto completo (ver su propio README ahí adentro
para instalarlo y correrlo paso a paso)
documentacion/
articulo/
estado-del-arte/ Primera versión del estado del arte
version-final/ Informe final del proyecto
presentaciones/ Presentaciones de avance
informe/
material_didactico/ Diagramas de arquitectura del sistema


## Cómo correrlo

Todos los pasos de instalación (Python, MongoDB, entorno virtual,
variables de entorno) están detallados en `codigo-fuente/README.md` y
en `codigo-fuente/GUIA_INSTALACION.md`.
