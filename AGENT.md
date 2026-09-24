# AGENT.md — webcam-bot

Guía para agentes (y personas) que trabajen en este repositorio: qué hace el
proyecto, cómo está organizado y qué convenciones seguir al modificarlo.

## Qué es

Bot de Telegram en Python que controla una webcam USB conectada a un servidor
Linux (`192.168.1.150`). Se despliega con Docker en ese mismo servidor.

Funcionalidades:

1. **Foto bajo demanda** — botón «📸 Hacer foto» o `/foto`: captura una imagen
   y la envía al chat.
2. **Vigilancia de perro** — botón «🐶 Vigilancia» o `/vigilancia`: un job
   periódico revisa la cámara y, si detecta un perro (MobileNet-SSD vía
   `cv2.dnn`), envía la foto a todos los usuarios autorizados. Se
   activa/desactiva con botones inline.
3. **Reset USB de la cámara** — botón «🔁 Reiniciar cámara» o `/reset_cam`:
   hace un reset a nivel de puerto USB (ioctl `USBDEVFS_RESET`) cuando la
   webcam se queda colgada, y luego verifica capturando una foto.

Otros comandos: `/start` (muestra el teclado de botones) y `/help`.

## Estructura

```
webcam-bot/
├── webcam_bot/             # Paquete del bot; se arranca con `python -m webcam_bot`
│   ├── __init__.py         # Docstring del proyecto
│   ├── __main__.py         # main(): setup_logging, Settings.from_env, build_app, run_polling
│   ├── app.py              # build_app(settings): valida config, registra handlers, programa vigilancia
│   ├── config.py           # Settings (dataclass inmutable) + setup_logging()
│   ├── auth.py             # is_authorized() y decorador @restricted
│   ├── camera.py           # Camera (captura + lock), CameraError, encode_jpeg()
│   ├── handlers.py         # cmd_*, callbacks, BUTTON_*, MAIN_KEYBOARD, register_handlers()
│   ├── watchdog.py         # load_detector(), watchdog_job, textos/teclado de vigilancia
│   ├── detection.py        # Detección de perro con MobileNet-SSD (OpenCV DNN), sin estado
│   └── usb_reset.py        # Reset USB real de la cámara vía sysfs + ioctl (solo Linux)
├── tests/                  # pytest: config, auth, detection, usb_reset (este último solo en Linux)
├── models/                 # Pesos del modelo (NO versionados, solo .gitkeep)
│   ├── MobileNetSSD_deploy.prototxt      (a descargar)
│   └── MobileNetSSD_deploy.caffemodel    (a descargar, ~23 MB)
├── requirements.txt        # python-telegram-bot[job-queue]==21.6, opencv-python-headless==4.10.0.84
├── requirements-dev.txt    # requirements.txt + pytest
├── pyproject.toml          # Solo configuración de herramientas (pytest); no se publica como paquete
├── Dockerfile              # python:3.12-slim + libglib2.0-0, libgl1, v4l-utils
├── docker-compose.yml      # Mapeo de /dev/video0, /dev/bus/usb y regla cgroup para USB
├── .env.example            # Plantilla de configuración
├── .gitignore
└── README.md               # Guía de instalación y despliegue para el usuario
```

Dependencias entre módulos (en una sola dirección, sin ciclos):
`__main__` → `app` → `handlers` → `watchdog`, `camera`, `auth`, `usb_reset`;
`watchdog` → `detection`, `camera`, `config`.

## Cómo funciona

### Estado compartido: `bot_data`

No hay estado global a nivel de módulo. `build_app()` guarda en
`app.bot_data` todo lo que comparten handlers y job:

| Clave | Contenido |
|---|---|
| `settings` | `Settings` inmutable leída del entorno al arrancar |
| `camera` | Instancia de `Camera` (incluye el `asyncio.Lock` del dispositivo) |
| `net` | Red de detección, o `None` si faltan los pesos o la JobQueue |
| `watchdog_job` | `Job` de vigilancia (se activa con `job.enabled`), o `None` |
| `last_dog_alert_ts` | `time.monotonic()` de la última alerta (cooldown) |

Importar cualquier módulo del paquete no lee el entorno ni configura el
logging: eso solo ocurre en `__main__.main()`.

### `config.py`

`Settings.from_env(env=None)` lee las variables de entorno (o el diccionario
que se le pase, útil en tests) y devuelve un `Settings` congelado.
`model_prototxt` / `model_weights` son propiedades derivadas de `model_dir`.
`MODEL_DIR` por defecto es `models/` en la raíz del proyecto.

### `auth.py`

`is_authorized(user, allowed_user_ids)` y el decorador `@restricted`, que lee
la lista de `context.bot_data["settings"]`. Si `ALLOWED_USER_IDS` está vacío,
**cualquier usuario** tiene acceso (se avisa en el log). Los callbacks inline
(`on_watchdog_callback`) comprueban la autorización a mano porque no llevan
`update.message`.

### `camera.py`

`Camera.read_frame_sync(warmup_frames)` abre el dispositivo, descarta N
fotogramas de calentamiento y devuelve el último; `encode_jpeg()` lo codifica
(calidad 90). La cámara se abre y se libera en **cada** captura; no hay
stream persistente. Errores esperables como `CameraError`.
`Camera.capture_jpeg(warmup_frames)` es la versión async (adquiere el lock y
usa `asyncio.to_thread`).

**Concurrencia**: todo acceso al dispositivo pasa por `camera.lock` y el
trabajo bloqueante de OpenCV/ioctl se ejecuta con `asyncio.to_thread`.
Cualquier código nuevo que toque la cámara debe respetar ambas cosas.

### `watchdog.py`

`load_detector(settings)` carga la red al arrancar; si faltan los pesos
devuelve `None` y la vigilancia se desactiva sin romper el bot.
`watchdog_job` se registra en `build_app()` con `app.job_queue.run_repeating`
(requiere el extra `job-queue`). Solo codifica a JPEG si hay detección
positiva, respeta el cooldown y envía la alerta a todos los
`allowed_user_ids`.

### `handlers.py`

`cmd_start`, `cmd_help`, `cmd_foto`, `cmd_vigilancia`, `cmd_reset_cam`,
`on_watchdog_callback` (patrón `^wd:`, datos `wd:on` / `wd:off`) y
`unknown_text`, que enruta el texto de los botones del teclado a su comando.
`register_handlers(app)` los registra todos.

### `app.py` y `__main__.py`

`build_app(settings)` valida `TELEGRAM_BOT_TOKEN`, crea la `Camera`, rellena
`bot_data`, registra handlers, carga el detector y programa el job.
`__main__.main()` configura el logging, lee `Settings` y hace `run_polling`.

### `detection.py`

Funciones puras sin estado global. `load_net()` carga el modelo Caffe;
`find_dog(net, frame, min_confidence)` devuelve `(encontrado, confianza)`.
`_best_dog_confidence()` está separado para poder probarlo con arrays
sintéticos sin la red real. El orden de `VOC_CLASSES` es crítico (índice de
salida de la red; `dog` = 12). `cv2` se importa dentro de las funciones.

### `usb_reset.py`

A partir de `/dev/videoN` resuelve `/sys/class/video4linux/videoN/device`,
sube por sysfs hasta el directorio con `busnum`/`devnum` (el dispositivo USB,
no la interfaz) y construye `/dev/bus/usb/BBB/DDD`. Después abre ese nodo y
ejecuta `ioctl(fd, USBDEVFS_RESET)`. Errores como `USBResetError`.
`_walk_up_for_usb_device()` está separado para probarlo con rutas sintéticas.
Usa `fcntl`, así que **solo funciona en Linux** (no se puede importar en
Windows).

## Configuración (variables de entorno)

| Variable | Defecto | Uso |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — (obligatoria) | Token de @BotFather |
| `ALLOWED_USER_IDS` | vacío = todos | IDs separados por comas; también son los destinatarios de las alertas |
| `CAMERA_DEVICE` | `/dev/video0` | Dispositivo de vídeo |
| `CAMERA_WIDTH` / `CAMERA_HEIGHT` | `1280` / `720` | Resolución solicitada |
| `WARMUP_FRAMES` | `10` | Fotogramas descartados en captura manual |
| `MODEL_DIR` | `./models` | Carpeta con los pesos del modelo |
| `DOG_WATCHDOG_ENABLED` | `true` | Estado inicial de la vigilancia |
| `DOG_CHECK_INTERVAL_SECONDS` | `5` | Periodo del job de vigilancia |
| `DOG_ALERT_COOLDOWN_SECONDS` | `60` | Tiempo mínimo entre alertas |
| `DOG_MIN_CONFIDENCE` | `0.4` | Umbral de detección |
| `DOG_CHECK_WARMUP_FRAMES` | `3` | Calentamiento en la vigilancia |
| `RESET_SETTLE_SECONDS` | `5` | Espera tras el reset USB antes de verificar |

Al añadir una variable nueva: añadir el campo a `Settings` en `config.py`
(con valor por defecto) y leerlo en `Settings.from_env()`, documentarla en
`.env.example` (y en el README si afecta al usuario).

## Ejecución y despliegue

Pensado para ejecutarse en el servidor Linux con Docker:

```bash
cp .env.example .env   # rellenar token y usuarios
docker compose up -d --build
docker compose logs -f
```

`docker-compose.yml` mapea `/dev/video0`, monta `/dev/bus/usb` y añade la
regla cgroup `c 189:* rmw` (necesarias para el reset USB) sin usar
`privileged: true`. Si aparece `Permission denied` con la cámara, descomentar
`group_add` con el GID del grupo `video`.

El `Dockerfile` copia el paquete completo (`COPY webcam_bot/`) y `models/`, y
arranca con `python -m webcam_bot`. Los módulos nuevos dentro del paquete se
incluyen solos.

En local (Windows, con `.venv`) no se puede ejecutar el bot completo:
`usb_reset.py` importa `fcntl` y no existe `/dev/video0`. Sí se pueden
ejecutar los tests:

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/test_usb_reset.py` se salta automáticamente en Windows.

## Convenciones

- Código, comentarios, logs y mensajes al usuario **en español**.
- Mensajes de Telegram con emoji al principio (`⚠️`, `✅`, `🔁`, `🐶`…).
- Funciones síncronas bloqueantes con sufijo `_sync` y ejecutadas vía
  `asyncio.to_thread`; helpers privados con prefijo `_`.
- Errores esperables con excepciones propias (`CameraError`, `USBResetError`)
  cuyo mensaje se muestra tal cual al usuario; errores inesperados con
  `logger.exception` y un mensaje genérico que remite a los logs.
- Las funciones opcionales degradan con elegancia: si falta el modelo o la
  JobQueue, el bot sigue funcionando sin vigilancia.
- Cada nuevo comando necesita (todo en `handlers.py`): handler con
  `@restricted`, registro en `register_handlers()`, entrada en `cmd_help` y
  `cmd_start`, y si tiene botón, la constante `BUTTON_*`, su fila en
  `MAIN_KEYBOARD` y la rama en `unknown_text`.
- Imports absolutos dentro del paquete (`from webcam_bot.camera import ...`).
- Cada módulo declara su API pública con `__all__`.
- Nada de estado global mutable ni efectos al importar: el estado compartido
  va en `bot_data` y la configuración en `Settings`.
- Tests con pytest en `tests/`; no hay linter configurado.

## Pendientes / incoherencias conocidas

- El README no incluye todavía la sección «Detección automática de perro»
  (instrucciones para descargar los pesos a `models/`), aunque el código y los
  logs la referencian. Tampoco documenta `/vigilancia` ni `/reset_cam`.
