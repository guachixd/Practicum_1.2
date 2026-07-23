# Generador de Recursos Didácticos — UTPL (interfaz web)

Aplicación web para generar recursos didácticos (resumen ejecutivo,
glosario, preguntas de comprensión y actividad de reflexión por unidad)
a partir del material de un curso, sin necesidad de tocar PyCharm ni
depender de un programador. Sin cuentas ni login: se abre la página y
se genera directamente.

## Qué cambió en esta versión

- **Menos llamadas a la API por documento.** Antes, cada unidad hacía 8
  llamadas a Gemini (4 para generar cada recurso por separado, 4 para
  evaluarlos por separado). Ahora son solo 2: una que genera los 4
  recursos juntos en un solo JSON, y otra que los evalúa juntos. Si algo
  del JSON viene incompleto, esa pieza puntual se pide aparte, sin
  repetir las demás.
- **Detección de estructura y clasificación de archivos con un modelo
  más liviano** (`gemini-2.5-flash-lite`), separado del que genera el
  contenido (`gemini-2.5-flash`). Como cada modelo tiene su propia
  cuota, esto evita que clasificar archivos consuma la cuota que hace
  falta para generar el contenido real.
- **Caché por archivo.** Si subes el mismo archivo (por contenido, no
  por nombre) que ya se clasificó antes, no se vuelve a mandar a
  Gemini — se reusa el resultado guardado.
- **Calificación de cada apartado en consola**, apenas se evalúa, y un
  resumen guardado junto con el trabajo (cuántos se aprobaron a la
  primera vs. cuántos necesitaron reformular).
- **Barra de progreso real** (unidad X de N) y botón para **pausar
  manualmente** la generación — se detiene entre unidades, nunca a
  mitad de una llamada a la IA, y se retoma después sin perder nada.
- **Vista previa con calificaciones.** Al terminar, "Ver recursos" te
  deja revisar cada apartado con su puntaje, marcar cualquier
  combinación (el resumen de la Unidad 2, el glosario de la Unidad 4,
  lo que sea) y regenerar solo esos, sin tocar el resto del documento.
  Se guarda la versión anterior antes de reemplazarla.
- **Consumo de la API más pausado.** Cada llamada a Gemini espera unos
  segundos antes de la siguiente (`SEGUNDOS_ENTRE_LLAMADAS_IA` en el
  `.env`, 4s por defecto), para no agotar el límite de solicitudes por
  minuto de la cuota gratuita tan rápido.
- **Tabla de costos en consola.** Al terminar (o pausarse, o fallar)
  cada generación, se imprime en la consola donde corre `python app.py`
  (la consola de PyCharm, si lo corres desde ahí) una tabla con los
  tokens **reales** que reportó la API de Gemini y el costo aproximado
  en dólares, por modelo y por asignatura. El costo total también queda
  guardado junto con el trabajo (se ve en el panel principal).
- **Sin login.** No hay usuarios, contraseñas ni panel de administración.
  El nombre del docente se pide como un dato más del formulario "Nuevo
  documento" (para la portada y la marca de agua), no como credencial.
- **Generación automática de unidades sin material propio.** Si una
  unidad del plan docente no tiene archivos propios subidos, igual se
  genera su documentación completa a partir del título y los temas del
  plan docente. Si ni siquiera hay un plan docente reconocible, la
  estructura de unidades se infiere del resto del material.
- **Un documento a la vez.** Todos los trabajos comparten la misma
  cuota de la API, así que no se permite generar o continuar dos al
  mismo tiempo — sale un aviso en pantalla si se intenta.
- **Recuperación de trabajos huérfanos.** Si el servidor se reinicia a
  media generación, el trabajo que quedó a medias se retoma solo al
  arrancar de nuevo.

## Estructura del proyecto

```
src/                  Pipeline (lógica)
  main.py              Uso por línea de comandos (se conserva, opcional)
  pipeline.py          Orquestador RESUMIBLE que usa la web
  bd.py                Base de datos: trabajos, unidades, recursos, evaluaciones
  extractor.py         Lectura de PDF/Word/PowerPoint
  clasificador.py      Detección de unidades + clasificación de archivos
  base_conocimiento.py Arma las unidades del curso
  generador_recursos.py Prompts + llamadas a Gemini
  evaluador.py         Evaluación automática (LLM-as-a-judge)
  exportador.py        Genera el Word final
  marca_agua.py        Marca de agua institucional
  reintentos.py        Reintentos + espaciado entre llamadas + CuotaAgotadaError
  costos.py            Seguimiento de tokens reales y tabla de costos en consola
webapp/
  app.py               Rutas de Flask (sin login)
  templates/           Páginas (panel, nuevo documento, subida, progreso)
  static/              CSS e imágenes (colores institucionales UTPL)
assets/
  logo_utpl.png        Logo institucional (marca de agua y portada)
data/
  material/<job_id>/   Archivos subidos por cada trabajo (se crea solo)
  salida/              Documentos Word generados (se crea solo)
requirements.txt
.env.example
```

## Instalación

1. Instala Python 3.11+ y MongoDB Community Server (local, corriendo en
   `mongodb://localhost:27017` por defecto).
2. Crea un entorno virtual e instala dependencias:

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # En Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Copia `.env.example` a `.env` (en la raíz del proyecto) y completa al
   menos `GEMINI_API_KEY`.

## Cómo correr la interfaz web

```bash
cd webapp
python app.py
```

Abre `http://localhost:5000` en el navegador:

1. Se ve directo el panel de "Mis documentos" (sin login). Presiona
   **"Nuevo documento"**.
2. Llena nombre del docente, carrera, ciclo académico, periodo,
   asignatura y código (esto también arma la portada y la marca de
   agua).
3. Sube el **plan docente** (recomendado, no obligatorio) y, si tiene,
   la **guía didáctica**; luego los **materiales adicionales**
   (diapositivas por semana, lecturas, etc. — no importa el nombre ni
   el orden de los archivos). Si no subes ningún plan docente, la
   estructura de unidades se detecta automáticamente a partir del resto
   del material.
4. Elige si el documento final lleva **marca de agua institucional** o
   no.
5. Observa el progreso en vivo. Mientras tanto, en la consola donde
   corre `python app.py` vas viendo el avance real y, al terminar (o
   pausarse), la tabla de costos aproximados de esa corrida. Si en
   algún momento se agotan los créditos/tokens de la IA, la pantalla lo
   indica y basta con presionar **"Continuar procesando"** más tarde
   para retomar justo donde se quedó.
6. Descarga el documento Word final desde "Mis documentos".

## Uso por línea de comandos (opcional, para pruebas locales)

`src/main.py` se conserva para correr el pipeline directamente sobre una
carpeta `data/material/` sin pasar por la web (útil para depurar). Usa
las mismas variables de entorno de siempre (`ASIGNATURA`,
`CODIGO_ASIGNATURA`, `NOMBRE_DOCENTE`, `RUTA_LOGO_UTPL`). Al terminar (o
si se queda sin créditos) imprime también la tabla de costos de esa
corrida. Si se queda sin créditos a media corrida, basta con volver a
correr el mismo comando para continuar donde se quedó (usa `JOB_ID_CLI`
para distinguir corridas de prueba en la base de datos si lo necesitas).

## Variables de entorno relevantes (`.env`)

- `GEMINI_API_KEY` — obligatoria.
- `MONGO_URI` — por defecto `mongodb://localhost:27017`.
- `SECRET_KEY` — usada por Flask para las cookies de sesión (mensajes
  flash); cualquier texto largo sirve, ya no protege ninguna cuenta.
- `SEGUNDOS_ENTRE_LLAMADAS_IA` — segundos de espera después de cada
  llamada exitosa a Gemini (por defecto `4`). Subir este valor consume
  la cuota todavía más lento; bajarlo a `0` la desactiva por completo
  (no recomendado si te quedas sin cuota seguido).
- `PORT` — puerto de la web (por defecto `5000`).

## Notas de despliegue

- El servidor de desarrollo de Flask (`python app.py`) alcanza para uso
  interno/piloto. Para un uso más formal, corre la app con un servidor
  WSGI de producción, por ejemplo:

  ```bash
  pip install gunicorn
  gunicorn -w 2 -b 0.0.0.0:5000 app:app
  ```

- La generación de cada documento corre en un hilo en segundo plano por
  trabajo; con `gunicorn` usa al menos 2 workers para que la pantalla de
  progreso pueda seguir consultando el estado mientras un trabajo se
  procesa.
- Como ya no hay cuentas, cualquier persona con acceso a la URL puede
  ver y descargar todos los documentos listados en el panel. Si vas a
  exponer esto más allá de tu propia máquina, considera ponerlo detrás
  de una VPN o de autenticación a nivel de red (no de la aplicación).
