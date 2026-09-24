# webcam-bot

Bot de Telegram que controla una webcam conectada al servidor. Al pulsar el
botón **«📸 Hacer foto»** (o enviar `/foto`), activa la cámara, captura una
imagen y te la envía por Telegram. Opcionalmente, también vigila la cámara
y te avisa con una foto cuando detecta un perro (ver sección 5).

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

## 5. Detección automática de perro

Además de las fotos bajo demanda, el bot puede vigilar la cámara por su
cuenta: cada pocos segundos captura una imagen y, si detecta un perro, envía
la foto a todos los usuarios de `ALLOWED_USER_IDS` sin que tengas que pulsar
nada.

La detección usa **MobileNet-SSD**, una red neuronal ligera que funciona en
CPU a través de OpenCV (no hace falta instalar nada más). Sus pesos (~23 MB)
**no se incluyen en el repositorio**: hay que descargarlos una vez. Sin
ellos, el bot funciona igual pero sin vigilancia.

### Descargar el modelo

Dentro de la carpeta del proyecto, en el servidor:

```bash
curl -L -o models/MobileNetSSD_deploy.prototxt \
  https://raw.githubusercontent.com/djmv/MobilNet_SSD_opencv/master/MobileNetSSD_deploy.prototxt
curl -L -o models/MobileNetSSD_deploy.caffemodel \
  https://raw.githubusercontent.com/djmv/MobilNet_SSD_opencv/master/MobileNetSSD_deploy.caffemodel
```

Comprueba que se han descargado bien (el `.caffemodel` debe ocupar unos
23 MB, no unos pocos bytes):

```bash
ls -l models/
```

Los archivos del modelo se copian dentro de la imagen de Docker, así que
hay que reconstruirla:

```bash
docker compose up -d --build
docker compose logs -f
```

En los logs deberías ver `Modelo de detección cargado desde ...` y
`vigilancia=disponible`. Si ves `No se encontraron los archivos del modelo`,
revisa que los nombres de los archivos sean exactamente los de arriba.

### Uso

Pulsa **«🐶 Vigilancia»** (o envía `/vigilancia`) para ver si está activada y
encenderla o apagarla con los botones «🟢 Activar» / «🔴 Desactivar».

Cuando detecta un perro recibirás la foto con el texto
`🐶 ¡Perro detectado! (confianza 87%)`. Para no llenarte el chat mientras el
perro sigue delante de la cámara, después de un aviso espera un tiempo
mínimo antes de enviar el siguiente.

Mientras la vigilancia está activada, la cámara se enciende cada pocos
segundos (el LED parpadeará). Es normal.

### Ajustes

En `.env` (reinicia con `docker compose up -d` tras cambiarlos):

| Variable | Por defecto | Para qué sirve |
|---|---|---|
| `DOG_WATCHDOG_ENABLED` | `true` | Si la vigilancia arranca activada. Siempre se puede cambiar luego desde Telegram |
| `DOG_CHECK_INTERVAL_SECONDS` | `5` | Cada cuántos segundos revisa la cámara |
| `DOG_ALERT_COOLDOWN_SECONDS` | `60` | Tiempo mínimo entre dos avisos |
| `DOG_MIN_CONFIDENCE` | `0.4` | Confianza mínima (0-1) para dar el aviso |
| `DOG_CHECK_WARMUP_FRAMES` | `3` | Fotogramas de calentamiento en cada revisión |

**Avisos cuando no hay perro (falsos positivos):** sube `DOG_MIN_CONFIDENCE`
(por ejemplo a `0.6`).
**No avisa aunque el perro esté delante:** bájalo (por ejemplo a `0.3`) y
comprueba que la cámara ve al perro de cuerpo entero y con buena luz; de
noche o a contraluz la detección empeora mucho.

Nota: el modelo reconoce perros como «clase», no a *tu* perro en concreto:
avisará con cualquier perro que aparezca en la imagen.

## 6. Reiniciar la cámara (reset USB)

A veces la webcam se queda «colgada»: el LED se queda encendido fijo y el bot
responde `La cámara se abrió pero no devolvió fotogramas` o `No se pudo abrir
el dispositivo de cámara`. Normalmente se arregla desenchufando y volviendo a
enchufar el cable USB; este comando hace lo mismo por software, sin tocar el
servidor.

### Uso

Pulsa **«🔁 Reiniciar cámara»** (o envía `/reset_cam`). El bot:

1. Hace un reset del puerto USB de la cámara (como si la desenchufaras y la
   volvieras a enchufar).
2. Espera unos segundos a que el sistema la vuelva a reconocer.
3. Hace una foto de prueba y te la envía con
   `✅ Cámara reiniciada y respondiendo correctamente.`

Si recibes `Reset USB realizado (...), pero la cámara aún no responde`, espera
unos segundos y prueba «📸 Hacer foto». Si sigue sin responder, sube
`RESET_SETTLE_SECONDS` en `.env` (por defecto `5`), que es cuánto espera el
bot antes de la foto de prueba.

Mientras dura el reset, la vigilancia de perro y las fotos se quedan en
espera, para que nada intente usar la cámara a medias.

### Requisitos

Solo funciona con el bot corriendo en Linux (en Docker, como se explica
aquí). El `docker-compose.yml` ya incluye lo necesario:

- `volumes: /dev/bus/usb:/dev/bus/usb`: el contenedor necesita ver los
  dispositivos USB, no solo `/dev/video0`.
- `device_cgroup_rules: "c 189:* rmw"`: permiso para acceder a dispositivos
  USB. Es mucho más restringido que `privileged: true`, pero da acceso a
  cualquier dispositivo USB del servidor, no solo a la cámara. El bot solo
  resetea el de la cámara.

Si quitas esas líneas, el resto del bot sigue funcionando, pero `/reset_cam`
fallará.

### Si el reset falla

**`No se pudo abrir /dev/bus/usb/... para el reset`**
Al contenedor le falta acceso a los dispositivos USB. Comprueba que las dos
líneas de arriba siguen en `docker-compose.yml` y recrea el contenedor con
`docker compose up -d`.

**`No se encontró la ruta sysfs de '/dev/video0'`**
El sistema ya no ve la cámara: probablemente se ha desconectado o ha
cambiado de nombre (por ejemplo, a `/dev/video1`). Compruébalo en el
servidor con `v4l2-ctl --list-devices`.

**El reset funciona pero la cámara sigue sin responder**
Algunos bloqueos no se arreglan por software. Desenchufa físicamente la
cámara, vuelve a enchufarla y reinicia el contenedor con
`docker compose restart`.

## 7. Solución de problemas

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

Si ningún proceso la está usando, puede que la cámara se haya quedado
colgada: prueba «🔁 Reiniciar cámara» (ver sección 6).

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
