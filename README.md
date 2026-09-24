# webcam-bot

Bot de Telegram que controla una webcam conectada al servidor. Al pulsar el
botón **«📸 Hacer foto»** (o enviar `/foto`), activa la cámara, captura una
imagen y te la envía por Telegram.

Pensado para desplegarse en Docker en el mismo servidor donde tienes
Server-bot, Pi-hole, etc. (`192.168.1.150`).

## 1. Requisitos previos

- Webcam USB conectada al servidor.
- Docker y Docker Compose instalados.

Comprueba que el servidor detecta la cámara:

```bash
ls -l /dev/video0
v4l2-ctl --list-devices   # si no lo tienes: sudo apt install v4l-utils
```

Si tu cámara aparece con otro nombre de dispositivo (`/dev/video1`, etc.),
lo ajustarás más abajo en `.env` y en `docker-compose.yml`.

## 2. Crear el bot en Telegram

1. Habla con **@BotFather** en Telegram.
2. `/newbot` → sigue las instrucciones → te da un **token** (algo como
   `123456789:AAbecerro...`).
3. Habla con **@userinfobot** para averiguar tu **ID de usuario** de Telegram
   (un número). Si vais a usarlo varias personas, apunta el ID de cada una.

## 3. Configurar

Copia el archivo de ejemplo y rellénalo:

```bash
cp .env.example .env
nano .env
```

```
TELEGRAM_BOT_TOKEN=el_token_de_botfather
ALLOWED_USER_IDS=123456789,987654321
CAMERA_DEVICE=/dev/video0
```

`ALLOWED_USER_IDS` es importante: sin restringirlo, cualquiera que
encuentre tu bot en Telegram podría ver la imagen de tu webcam.

## 4. Desplegar

Copia esta carpeta al servidor (`192.168.1.150`) y, dentro de ella:

```bash
docker compose up -d --build
docker compose logs -f
```

Deberías ver `webcam-bot arrancando (...)`. Abre el chat con tu bot en
Telegram, pulsa `/start` y luego «📸 Hacer foto».

## 5. Solución de problemas

**`Permission denied` al abrir /dev/video0 en los logs**
El usuario dentro del contenedor no pertenece al grupo del dispositivo.
Consulta el GID del grupo `video` en el servidor:

```bash
getent group video
```

Descomenta `group_add` en `docker-compose.yml` y pon ese GID en vez de
`"44"`, luego `docker compose up -d --build`.

**La cámara nunca se abre / "No se pudo abrir el dispositivo"**
Otro proceso la tiene abierta (por ejemplo, otra instancia del contenedor
corriendo, o un stream previo sin cerrar). Comprueba con:

```bash
sudo fuser /dev/video0
```

**Fotos oscuras, verdosas o con colores raros**
Sube el valor de `WARMUP_FRAMES` en `.env` (por ejemplo a 20-30): algunas
webcams tardan varios fotogramas en ajustar la exposición y el balance de
blancos tras encenderse.

**Quiero más resolución**
Ajusta `CAMERA_WIDTH` / `CAMERA_HEIGHT` en `.env`. Si la webcam no soporta
esa resolución exacta, OpenCV usará la más cercana disponible.

## Estructura del proyecto

```
webcam-bot/
├── webcam_bot/         # Código del bot (se arranca con `python -m webcam_bot`)
│   ├── __main__.py     # Punto de entrada
│   ├── app.py          # Construcción de la aplicación de Telegram
│   ├── config.py       # Configuración leída de variables de entorno
│   ├── auth.py         # Control de usuarios autorizados
│   ├── camera.py       # Captura de imagen
│   ├── handlers.py     # Comandos y botones de Telegram
│   ├── watchdog.py     # Vigilancia automática de perro
│   ├── detection.py    # Detección de perro (MobileNet-SSD)
│   └── usb_reset.py    # Reset USB de la cámara
├── tests/              # Tests (`pytest`)
├── models/             # Pesos del modelo de detección (no versionados)
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml      # Configuración de pytest
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Próximos pasos posibles (no implementados)

- Comando para grabar un vídeo corto en vez de una foto.
- Botones inline para elegir resolución/calidad al vuelo.
- Notificación automática por detección de movimiento.
