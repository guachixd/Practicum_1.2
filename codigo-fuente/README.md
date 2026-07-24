# Cómo correr mi proyecto — Generador de Recursos Didácticos

Ingeniero, aquí le explico paso a paso cómo dejar corriendo mi proyecto
en su computadora. Hay algunas cosas que no subí al repositorio a
propósito (mi entorno virtual, mi clave de la API, y los archivos de
prueba que subí mientras probaba) — aquí le explico por qué y cómo
recrearlas fácil, no debería tomarle más de 10-15 minutos.

## Por qué faltan algunas cosas

| Cosa | ¿Está en el repo? | Por qué no la subí |
|---|---|---|
| Mi código (`src/`, `webapp/`) | Sí | Es el proyecto en sí |
| El logo de la UTPL (`assets/`) | Sí | Lo necesita el programa para la marca de agua |
| `requirements.txt` | Sí | Ahí indico qué librerías hacen falta |
| `.env.example` | Sí | Es la plantilla, sin mi clave real |
| Mi `.env` con mi clave de la API | No | Es mi clave personal, no se sube nunca a un repositorio |
| Mi carpeta `.venv` | No | Pesa muchísimo y se recrea con un solo comando |
| Los PDFs que subí de prueba | No | Eran material de una asignatura de otro profesor, no es parte del proyecto |

Nada de esto se me olvidó subir — es a propósito, y aquí explico cómo
recrear cada cosa.

## Requisitos previos

- **Python 3.11 o más reciente.** Para verificar si ya lo tiene, abra
  una terminal (en Windows, PowerShell) y escriba:

python --version

  Si no reconoce el comando, pruebe con `py --version`. Si tampoco,
  más abajo explico cómo instalarlo.

- **MongoDB Community Server**, corriendo en su computadora. Ahí es
  donde el programa guarda todo lo que va generando. Más abajo también
  explico cómo instalarlo si no lo tiene.

- **Una clave de la API de Gemini** (es gratuita). Se obtiene en
  aistudio.google.com/apikey con cualquier cuenta de Google, con el
  botón "Create API key".

## Si no tiene Python instalado

En Windows, desde PowerShell:

winget install -e --id Python.Python.3.12

Después de instalarlo, cierre la terminal y abra una nueva para que
lo reconozca.

## Si no tiene MongoDB instalado

Se descarga de mongodb.com/try/download/community, se elige el
sistema operativo correspondiente, y se instala dejando todas las
opciones por defecto (en Windows, marcando la opción de instalarlo
como servicio, para que arranque solo cada vez que se prenda la
computadora). No hace falta configurar usuario ni contraseña; el
proyecto se conecta directo a `mongodb://localhost:27017` sin pedir
autenticación.

## Paso a paso

### 1. Descargue el proyecto

Del repositorio (botón "Code" → "Download ZIP" en GitHub) y
descomprímalo donde prefiera.

### 2. Abra una terminal en la carpeta raíz

Es la carpeta que tiene `requirements.txt`, `src/`, `webapp/`,
`assets/` y `data/` todos juntos, al mismo nivel.

### 3. Cree el entorno virtual

python -m venv .venv

(si `python` no funciona, use `py -m venv .venv`)

Esto crea la carpeta `.venv` que no subí al repositorio — es donde
queda instalado Python solo para este proyecto.

### 4. Actívelo

En Windows (PowerShell):

..venv\Scripts\Activate.ps1

Si sale un error de "ejecución de scripts deshabilitada", corra esto
una sola vez:

Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

(va a preguntar; se responde que sí) y se vuelve a intentar activar.

Se sabe que funcionó porque la terminal empieza a mostrar `(.venv)` al
inicio de la línea.

### 5. Instale las dependencias

Con el `(.venv)` ya activado:

pip install -r requirements.txt

Tarda 1-2 minutos. Al final no debe salir ninguna línea en rojo con
"ERROR".

### 6. Cree su propio `.env`

Copie el archivo `.env.example` que sí está en el repositorio, y
renombre la copia a `.env` (sin el ".example"). Ábralo y complete su
propia clave real:

GEMINI_API_KEY=su_clave_aqui

Lo demás ya viene con valores que funcionan, no hace falta modificar
nada más para una primera prueba.

### 7. Verifique que MongoDB esté corriendo

Si se instaló como servicio, ya debería estar activo. Si no está
seguro, revise el Administrador de tareas buscando `mongod.exe`.

### 8. Corra la aplicación

cd webapp
python app.py

Cuando la consola muestre `Running on http://127.0.0.1:5000`, abra esa
dirección en el navegador.

### 9. Pruebe el flujo completo

1. En el panel principal, presione "Nuevo documento".
2. Complete los datos generales (nombre del docente, asignatura,
   código, etc.).
3. Suba el material de una asignatura (si incluye el plan docente
   mejor, pero no es obligatorio — si no lo sube, el sistema detecta
   las unidades a partir del resto del material).
4. Elija si desea marca de agua institucional o no.
5. Observe el progreso en vivo, con una barra que indica en qué unidad
   va. En la consola donde corre `python app.py` también se ve la
   calificación que le asigna la IA a cada apartado, y al final una
   tabla con el costo real en dólares de esa generación.
6. Al terminar, revise "Ver recursos" para ver cada apartado con su
   calificación antes de descargar el documento Word final.

## Variables del `.env`

- `GEMINI_API_KEY` — la única obligatoria.
- `MONGO_URI` — no hace falta modificarla si MongoDB está instalado de
  forma estándar.
- `SECRET_KEY` — la usa Flask internamente, cualquier texto largo
  sirve.
- `SEGUNDOS_ENTRE_LLAMADAS_IA` — cuánto espera entre cada llamada a la
  IA para no agotar la cuota tan rápido (por defecto 4 segundos).
- `PORT` — el puerto de la web (por defecto 5000).

## Errores comunes

- **"No module named 'flask'"**: no se activó el entorno virtual, o se
  corrió `pip install` en la carpeta equivocada. Verifique que la
  terminal muestre `(.venv)` al inicio.

- **"No se pudo conectar a MongoDB"**: el servicio de MongoDB no está
  corriendo.

- **"No se encontró GEMINI_API_KEY"**: todavía no se creó el `.env`, o
  la clave quedó vacía o con texto extra pegado por error en la misma
  línea.

- **Se agota la cuota de la API rápido**: es normal, el nivel gratuito
  de Gemini da pocas solicitudes al día. Por eso el programa se pausa
  solo cuando esto ocurre (aparece un aviso claro en pantalla) y con el
  botón "Continuar procesando" retoma exactamente donde se quedó, sin
  repetir nada.
