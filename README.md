# webcam-bot

Bot de Telegram que controla una webcam conectada al servidor. Al pulsar el
botón **«📸 Hacer foto»** (o enviar `/foto`), activa la cámara, captura una
imagen y te la envía por Telegram. Opcionalmente, también vigila la cámara
y te avisa con una foto cuando detecta un perro (ver sección 5), y puede
reproducir un audio para que el perro deje de ladrar (ver sección 7).

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

## 7. Anti-ladridos

Con un micrófono y un altavoz conectados al servidor, el bot escucha
continuamente y, cuando oye ladrar:

1. Hace hasta 3 fotos (una por segundo) buscando al perro con el detector de
   la sección 5.
2. **Si ve al perro**: reproduce tu audio por el altavoz y te envía la foto
   con `🔊 Ladrido detectado (...) y perro a la vista`.
3. **Si no lo ve**: no reproduce nada y te envía la foto con
   `👂 Oigo un ladrido pero no veo ningún perro en la cámara`.

Después de actuar espera un tiempo mínimo (60 s por defecto) antes de volver
a hacerlo. Mientras suena el audio no escucha, para que el propio audio no
cuente como otro ladrido.

### Qué necesitas

- El **detector de perro** de la sección 5 (sin él no puede comprobar con la
  cámara).
- El **modelo de ladridos**: `ladridos.tflite` y `ladridos_info.json`. Se
  generan con el notebook `notebooks/entrenar_ladridos.ipynb` en Google Colab
  (instrucciones dentro del propio notebook). Cópialos a `models/`.
- Un **micrófono** y un **altavoz** conectados al servidor.
- Tu **audio** en formato WAV, guardado como `sounds/ladrido.wav`. Si lo
  tienes en MP3 u otro formato, conviértelo con:

  ```bash
  ffmpeg -i mi_audio.mp3 sounds/ladrido.wav
  ```

  Evita que el audio contenga ladridos: el micrófono podría oírlo.

### Configurar el micrófono y el altavoz

Hay que decirle al bot qué tarjeta de sonido es el micrófono y cuál el
altavoz. **No lo dejes en `default`**: la tarjeta por defecto suele ser la
primera que detecta el sistema, que puede ser la propia webcam (solo tiene
micrófono, no salida de audio) y además puede cambiar al reiniciar.

**1. Mira qué tarjetas hay.** En el servidor (si no tienes estos comandos:
`sudo apt install alsa-utils`):

```bash
arecord -l   # tarjetas con micrófono
aplay -l     # tarjetas con salida de audio
```

Por ejemplo, `card 1: PCH [HDA Intel PCH], device 0: ... Analog` es el audio
integrado del servidor, donde van los jacks de micrófono y de altavoz. Un
dispositivo de sonido USB aparecería como otra tarjeta con su propio nombre.

Ojo: muchos «altavoces USB» solo usan el USB para la **alimentación** y el
sonido les llega por un cable jack aparte. Si tu altavoz no aparece en
`aplay -l`, es de estos: conecta su cable jack a la salida de altavoz o
auriculares del servidor y usa la tarjeta del audio integrado.

**2. Comprueba que el servidor detecta los cables en los jacks:**

```bash
amixer -c PCH contents | grep -A2 "Jack"
```

`values=on` en `Headphone Jack` (o `Front Headphone Jack`) significa que
hay algo conectado a la salida de altavoz, y en `Mic Jack` (o
`Front Mic Jack`), al micrófono.

**3. Sube y activa los volúmenes.** Es muy habitual que las salidas y el
micrófono empiecen **silenciados**: `aplay` reproduce sin dar error, pero no
se oye nada. Actívalos con:

```bash
amixer -c PCH sset Master 80% unmute
amixer -c PCH sset Headphone 100% unmute
amixer -c PCH sset Capture 80% cap
```

Si alguno responde `Unable to find simple control`, ignóralo: tu tarjeta no
tiene ese control. Para verlo de forma visual, `alsamixer -c PCH`: las
columnas con `MM` debajo están silenciadas (selecciónalas con las flechas y
pulsa `M`); `F4` muestra los volúmenes del micrófono. Si hay una opción
`Auto-Mute Mode`, ponla en `Disabled`.

**4. Prueba el micrófono y el altavoz** (graba 5 segundos y los reproduce):

```bash
arecord -D plughw:CARD=PCH,DEV=0 -d 5 -f S16_LE -r 16000 prueba.wav
aplay -D plughw:CARD=PCH,DEV=0 prueba.wav
aplay -D plughw:CARD=PCH,DEV=0 sounds/ladrido.wav
```

**5. Guarda los volúmenes** para que se mantengan al reiniciar el servidor:

```bash
sudo alsactl store
```

**6. Pon los dispositivos en `.env`.** El formato es
`plughw:CARD=<nombre de la tarjeta>,DEV=<número de device>`. Usa siempre
`plughw:`, que adapta el audio al formato de la tarjeta. Si micrófono y
altavoz van a los jacks del audio integrado, es la misma tarjeta para los
dos (uno es entrada y el otro salida):

```
AUDIO_INPUT_DEVICE=plughw:CARD=PCH,DEV=0
AUDIO_OUTPUT_DEVICE=plughw:CARD=PCH,DEV=0
```

Aplica los cambios de `.env` con `docker compose up -d` (con `restart` no
se vuelve a leer el `.env`).

### Desplegar

`docker-compose.yml` ya da acceso al contenedor a las tarjetas de sonido
(`/dev/snd`) y monta la carpeta `sounds/`. Tras copiar los archivos:

```bash
docker compose up -d --build
docker compose logs -f
```

En los logs deberías ver `Modelo de ladridos cargado`, `Micrófono '...'
abierto` y `anti-ladridos=disponible`. Después, envía `/diagnostico` al bot
para comprobar que el micrófono y el altavoz funcionan (ver sección 8).

Para cambiar el audio más adelante no hace falta reconstruir la imagen: sustituye
`sounds/ladrido.wav` y ejecuta `docker compose restart`.

### Uso

Pulsa **«🔊 Anti-ladridos»** (o envía `/ladridos`) para ver si está activado y
encenderlo o apagarlo con los botones «🟢 Activar» / «🔴 Desactivar».

### Ajustes

En `.env` (reinicia con `docker compose up -d` tras cambiarlos):

| Variable | Por defecto | Para qué sirve |
|---|---|---|
| `BARK_GUARD_ENABLED` | `true` | Si arranca activado. Siempre se puede cambiar desde Telegram |
| `AUDIO_INPUT_DEVICE` | `default` | Micrófono (ver arriba) |
| `AUDIO_OUTPUT_DEVICE` | `default` | Altavoz (ver arriba) |
| `BARK_SOUND_FILE` | `/app/sounds/ladrido.wav` | Audio que se reproduce |
| `BARK_THRESHOLD` | el de `ladridos_info.json` (0,5) | Probabilidad mínima (0-1) para considerar que es un ladrido |
| `BARK_ALERT_COOLDOWN_SECONDS` | `60` | Tiempo mínimo entre dos actuaciones |
| `BARK_CAMERA_CHECKS` | `3` | Fotos (una por segundo) buscando al perro |

**Avisa de ladridos que no lo son** (tele, golpes...): sube `BARK_THRESHOLD`
(por ejemplo a `0.8`).
**No reacciona cuando ladra**: bájalo (por ejemplo a `0.3`) y comprueba el
volumen del micrófono con `alsamixer`.
**Oye el ladrido pero casi nunca ve al perro**: sube `BARK_CAMERA_CHECKS`
para darle más tiempo a entrar en el plano.

La mejor forma de reducir errores es reentrenar el modelo con grabaciones de
tu perro y del ruido de tu casa hechas con este mismo micrófono (ver la
sección 3 del notebook).

### Si algo falla

**`anti-ladridos=no disponible` en los logs**
Mira los avisos anteriores: faltan `ladridos.tflite` / `ladridos_info.json`
en `models/`, o falta el detector de perro.

**`El micrófono '...' se ha cerrado`**
El nombre en `AUDIO_INPUT_DEVICE` no es correcto o el micrófono no está
conectado. Comprueba el nombre con `arecord -L` y prueba a grabar como se
explica arriba. El bot vuelve a intentarlo cada 30 segundos.

**`⚠️ Pero no se pudo reproducir` en el aviso de Telegram**
El mensaje incluye el motivo. Normalmente es que `sounds/ladrido.wav` no
existe o que `AUDIO_OUTPUT_DEVICE` no es correcto. Si el motivo es
`unable to open slave` o `audio open error` con el dispositivo `'default'`,
es que falta configurar `AUDIO_OUTPUT_DEVICE` (ver
«Configurar el micrófono y el altavoz»).

**El aviso dice que reproduce el audio pero no se oye nada**
Prueba en el servidor con `aplay -D <tu dispositivo> sounds/ladrido.wav`.
Si pone `Playing WAVE ...` pero no suena, el volumen está silenciado o el
altavoz no está conectado a esa salida: revisa los pasos 2 y 3 de
«Configurar el micrófono y el altavoz».

**No detecta ningún ladrido**
Comprueba que el micrófono graba (paso 4) y que su volumen no está
silenciado (`Capture` en el paso 3).

## 8. Solución de problemas

**Diagnóstico rápido: `/diagnostico`**
Envía `/diagnostico` al bot y en unos segundos te responde con el estado de
todo:

```
🩺 Diagnóstico
📷 Cámara: ✅ responde (foto adjunta)
🎤 Micrófono: ✅ recibe sonido (nivel -40 dB; 0 es el máximo)
🔊 Altavoz: ✅ pitido reproducido. ¿Lo has oído?
    🎤 El micrófono lo ha captado ✅
🧠 Modelos: perro ✅ · ladridos ✅ (umbral 50%, activado)
```

- **Cámara**: hace una foto y te la envía.
- **Micrófono**: mide el volumen de 3 segundos de audio y te envía la
  grabación (`microfono.wav`) para que escuches lo que oye. Si pone
  «no llega sonido», está silenciado o es otro micrófono (sección 7,
  «Configurar el micrófono y el altavoz»).
- **Altavoz**: reproduce un pitido corto y comprueba si el micrófono lo
  capta. Si lo capta, altavoz y micrófono funcionan. Si no, puede que solo
  estén lejos o con el volumen bajo: comprueba si lo has oído.
- **Modelos**: si están cargados el detector de perro y el de ladridos.

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
│   ├── bark_guard.py   # Anti-ladridos: ladrido → cámara → audio + aviso
│   ├── bark_detection.py # Detección de ladridos (modelo de Colab)
│   ├── audio.py        # Micrófono y altavoz (arecord / aplay)
│   └── usb_reset.py    # Reset USB de la cámara
├── tests/              # Tests (`pytest`)
├── notebooks/          # Entrenamiento del detector de ladridos (Google Colab)
├── models/             # Modelos de perro y de ladridos (no versionados)
├── sounds/             # Audio del anti-ladridos (no versionado)
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
