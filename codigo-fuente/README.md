# Guía de instalación y ejecución — Generador de Recursos Didácticos (UTPL)

Esta guía explica, paso a paso, cómo dejar el proyecto corriendo igual
que en el entorno original. Como el repositorio **no incluye** ciertos
archivos a propósito (el entorno virtual, la clave de API, y el
material de prueba subido), aquí se explica exactamente cómo recrear
cada uno.

## Qué SÍ está en el repositorio y qué NO, y por qué

| Elemento | ¿Está en el repo? | Por qué |
|---|---|---|
| Código fuente (`src/`, `webapp/`) | Sí | Es el proyecto en sí |
| `assets/logo_utpl.png` | Sí | Necesario para la marca de agua y la portada |
| `requirements.txt` | Sí | Lista de librerías necesarias |
| `.env.example` | Sí | Plantilla de configuración, sin datos reales |
| `.env` (con la clave real de la API) | **No** | Contiene una clave privada; nunca se sube a un repositorio |
| `.venv/` (entorno virtual de Python) | **No** | Se recrea localmente con un comando; subirlo pesaría muchísimo |
| `data/material/` (PDFs de prueba subidos) | **No** (o vacío) | Material de ejemplo de una asignatura específica, no es parte del código |
| `data/salida/` (Word ya generados) | **No** (o vacío) | Se generan solos al usar el programa |

Ninguno de estos faltantes es un error: hay que **crearlos de nuevo**
siguiendo esta guía, y en unos 10-15 minutos queda todo funcionando.

---

## Requisitos previos

- **Python 3.11 o superior**. Para verificar si ya está instalado, abre
  una terminal (PowerShell en Windows, Terminal en Mac/Linux) y escribe:

python --version

  Si no lo reconoce, prueba con `py --version`. Si tampoco, hay que
  instalarlo (ver sección "Instalar Python" más abajo).

- **MongoDB Community Server**, corriendo localmente. El programa
  guarda ahí todo lo que genera (unidades, recursos, evaluaciones,
  costos). Ver sección "Instalar MongoDB" más abajo si no lo tienes.

- **Una clave de API de Google Gemini** (gratuita). Se obtiene en
  [aistudio.google.com/apikey](https://aistudio.google.com/apikey) con
  cualquier cuenta de Google — botón "Create API key".

---

## Instalar Python (si no lo tienes)

**Windows**, desde PowerShell:

winget install -e --id Python.Python.3.12

Cierra y vuelve a abrir la terminal después de instalar, para que
reconozca el comando nuevo.

**Mac**, con Homebrew:

brew install python@3.12


**Linux (Debian/Ubuntu)**:

sudo apt install python3 python3-venv python3-pip


---

## Instalar MongoDB Community Server (si no lo tienes)

Descárgalo de [mongodb.com/try/download/community](https://www.mongodb.com/try/download/community),
elige tu sistema operativo, e instálalo con las opciones por defecto
(en Windows, marca la opción de "Instalar como servicio" para que
arranque solo). No hace falta configurar usuarios ni contraseñas para
uso local — el proyecto se conecta a `mongodb://localhost:27017` por
defecto, sin autenticación.

Para confirmar que está corriendo (Windows): abre el "Administrador de
tareas" y busca un proceso llamado `mongod.exe`. Si no aparece, busca
"Servicios" en el menú de inicio y arranca el servicio "MongoDB Server".

---

## Paso a paso para dejar el proyecto corriendo

### 1. Descarga o clona el repositorio

Descarga el código (botón "Code" → "Download ZIP" en GitHub, o
`git clone` si prefieres línea de comandos) y descomprímelo en una
carpeta de tu elección.

### 2. Abre una terminal en la carpeta raíz del proyecto

La carpeta raíz es la que tiene `requirements.txt`, `src/`, `webapp/`,
`assets/` y `data/` todos al mismo nivel.

### 3. Crea el entorno virtual (no viene incluido en el repositorio)

python -m venv .venv

(si `python` no funciona, usa `py -m venv .venv`)

Esto crea una carpeta `.venv/` nueva con una instalación aislada de
Python solo para este proyecto — es justo la carpeta que no se sube al
repositorio.

### 4. Activa el entorno virtual

- **Windows (PowerShell)**:

..venv\Scripts\Activate.ps1

  Si aparece un error de "ejecución de scripts deshabilitada", corre
  esto una sola vez y vuelve a intentar:

Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

  (responde `S` cuando pregunte)

- **Mac / Linux**:

source .venv/bin/activate


Sabes que funcionó porque la línea de la terminal empieza a mostrar
`(.venv)` al inicio.

### 5. Instala las dependencias

Con el entorno virtual ya activado:

pip install -r requirements.txt

Tarda 1-2 minutos. Al final no debe haber ninguna línea en rojo con
"ERROR".

### 6. Crea tu archivo `.env` (no viene incluido, por seguridad)

Copia el archivo `.env.example` que sí está en el repositorio, y
renombra la copia a `.env` (sin ".example"). Ábrelo y completa al
menos esta línea con tu propia clave real:

GEMINI_API_KEY=tu_clave_real_aqui

Las demás variables ya tienen valores por defecto razonables y no hace
falta tocarlas para una primera prueba (ver la sección de variables
más abajo si quieres ajustarlas).

### 7. Confirma que MongoDB esté corriendo

Si lo instalaste como servicio, ya debería estar activo. Si no estás
seguro, revisa el "Administrador de tareas" (Windows) buscando
`mongod.exe`, o corre `mongosh` en una terminal aparte para confirmar
que conecta sin error.

### 8. Corre la aplicación web

cd webapp
python app.py

Cuando la consola muestre `Running on http://127.0.0.1:5000`, abre esa
dirección en el navegador.

### 9. Prueba el flujo completo

1. En el panel principal, presiona "Nuevo documento".
2. Llena los datos generales (nombre del docente, asignatura, código,
   etc.).
3. Sube el material de una asignatura (idealmente el plan docente,
   aunque no es obligatorio — si no lo subes, la estructura de
   unidades se infiere del resto del material).
4. Elige si quieres marca de agua institucional.
5. Observa el progreso en vivo. En la consola donde corre `python
   app.py` puedes ver el avance real, la calificación de cada apartado,
   y al finalizar, una tabla con el costo aproximado en dólares de esa
   generación (con los tokens reales que reportó la API de Gemini).
6. Al terminar, revisa "Ver recursos" para ver cada apartado con su
   calificación, y descarga el documento Word final.

---

## Variables de entorno (`.env`) explicadas

| Variable | Obligatoria | Qué hace |
|---|---|---|
| `GEMINI_API_KEY` | Sí | Tu clave personal de la API de Gemini |
| `MONGO_URI` | No | Dirección de MongoDB (por defecto `mongodb://localhost:27017`, no tocar si es instalación local estándar) |
| `SECRET_KEY` | No | Usada por Flask internamente para las cookies de sesión; cualquier texto largo sirve |
| `SEGUNDOS_ENTRE_LLAMADAS_IA` | No | Segundos de espera después de cada llamada a Gemini, para no agotar la cuota por minuto (por defecto 4) |
| `PORT` | No | Puerto de la web (por defecto 5000) |

---

## Uso alternativo por línea de comandos (sin la interfaz web)

Para pruebas rápidas sin pasar por el navegador, `src/main.py` corre el
mismo pipeline directamente sobre lo que haya en `data/material/`:

cd src
python main.py

Usa las variables `ASIGNATURA`, `CODIGO_ASIGNATURA` y `NOMBRE_DOCENTE`
del mismo `.env` para identificar la corrida.

---

## Problemas comunes al replicar el entorno

- **"No module named 'flask'" (o cualquier otro módulo)**: el entorno
  virtual no está activado, o el `pip install` se corrió en la carpeta
  equivocada. Verifica que la terminal muestre `(.venv)` al inicio y
  que estés en la carpeta raíz del proyecto al correr `pip install`.

- **"No se pudo conectar a MongoDB"**: el servicio de MongoDB no está
  corriendo. Revisa la sección de instalación de MongoDB más arriba.

- **"No se encontró GEMINI_API_KEY"**: el archivo `.env` no existe
  todavía, o existe pero está vacío en esa línea, o tiene texto extra
  pegado por accidente junto a la clave (revisa que la línea diga
  únicamente `GEMINI_API_KEY=` seguido de la clave, sin espacios ni
  texto adicional).

- **Se agota la cuota de la API muy rápido**: el nivel gratuito de
  Gemini tiene límites de solicitudes por día bastante bajos. El
  proyecto ya está diseñado para pausarse solo cuando esto pasa (verás
  un aviso claro en pantalla) y retomar exactamente donde se quedó con
  el botón "Continuar procesando" — no hay que reiniciar nada.
