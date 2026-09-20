"""
webcam-bot
----------
Bot de Telegram que controla una webcam conectada al servidor.

- Botón "📸 Hacer foto" (o /foto): captura una imagen bajo demanda y te
  la envía.
- Vigilancia automática (opcional): revisa la cámara periódicamente y,
  si detecta un perro, te envía la foto sola — sin que pulses nada.
  Se activa/desactiva con el botón "🐶 Vigilancia" o /vigilancia.

Pensado para desplegarse en Docker en el mismo servidor Linux donde está
conectada la webcam (ver docker-compose.yml para el mapeo del dispositivo).
"""

import asyncio
import logging
import os
import sys
import time
from functools import wraps

import cv2
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import detection
import usb_reset
# --------------------------------------------------------------------------
# Configuración (vía variables de entorno, ver .env.example)
# --------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_IDS = {
    int(uid.strip())
    for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
}
CAMERA_DEVICE = os.environ.get("CAMERA_DEVICE", "/dev/video0")
CAMERA_WIDTH = int(os.environ.get("CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "720"))
# Nº de fotogramas que se descartan al abrir la cámara para que el sensor
# ajuste exposición/balance de blancos antes de capturar el definitivo.
WARMUP_FRAMES = int(os.environ.get("WARMUP_FRAMES", "10"))

# --- Vigilancia / detección de perro ---
MODEL_DIR = os.environ.get(
    "MODEL_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
)
MODEL_PROTOTXT = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.prototxt")
MODEL_WEIGHTS = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.caffemodel")

DOG_WATCHDOG_DEFAULT = os.environ.get("DOG_WATCHDOG_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
DOG_CHECK_INTERVAL_SECONDS = float(os.environ.get("DOG_CHECK_INTERVAL_SECONDS", "5"))
DOG_ALERT_COOLDOWN_SECONDS = float(os.environ.get("DOG_ALERT_COOLDOWN_SECONDS", "60"))
DOG_MIN_CONFIDENCE = float(os.environ.get("DOG_MIN_CONFIDENCE", "0.4"))
# Menos fotogramas de calentamiento que en la captura manual: esta
# comprobación se repite cada pocos segundos y no necesita máxima calidad.
DOG_CHECK_WARMUP_FRAMES = int(os.environ.get("DOG_CHECK_WARMUP_FRAMES", "3"))

# --- Reset USB de la cámara ---
# Segundos de margen tras el reset antes de intentar verificarlo con una
# captura (el driver/kernel tarda un poco en volver a enumerar el
# dispositivo).
RESET_SETTLE_SECONDS = float(os.environ.get("RESET_SETTLE_SECONDS", "3"))

BUTTON_PHOTO = "📸 Hacer foto"
BUTTON_WATCHDOG = "🐶 Vigilancia"
BUTTON_RESET = "🔁 Reiniciar cámara"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("webcam-bot")

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[BUTTON_PHOTO], [BUTTON_WATCHDOG], [BUTTON_RESET]], resize_keyboard=True, is_persistent=True
)

# Serializa el acceso al dispositivo de la cámara: solo un lector a la vez
# (evita que la captura manual y la vigilancia periódica choquen).
camera_lock = asyncio.Lock()

# Red de detección cargada una vez al arrancar (None si faltan los pesos)
_net = None


# --------------------------------------------------------------------------
# Autorización
# --------------------------------------------------------------------------

def _is_authorized(user) -> bool:
    return bool(user) and (not ALLOWED_USER_IDS or user.id in ALLOWED_USER_IDS)


def restricted(handler):
    """Rechaza silenciosamente (con aviso) a usuarios no autorizados."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not _is_authorized(user):
            logger.warning(
                "Acceso denegado a user_id=%s (%s)",
                getattr(user, "id", "desconocido"),
                getattr(user, "username", "sin username"),
            )
            if update.message:
                await update.message.reply_text(
                    "⛔ No tienes permiso para usar este bot."
                )
            return
        return await handler(update, context)

    return wrapper


# --------------------------------------------------------------------------
# Captura de imagen
# --------------------------------------------------------------------------

class CameraError(Exception):
    pass


def _open_camera() -> cv2.VideoCapture:
    cap = cv2.VideoCapture(CAMERA_DEVICE)
    if not cap.isOpened():
        raise CameraError(
            f"No se pudo abrir el dispositivo de cámara '{CAMERA_DEVICE}'. "
            "¿Está conectada y mapeada al contenedor?"
        )
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    return cap


def _read_frame_sync(warmup_frames: int):
    """Abre la cámara, descarta fotogramas de calentamiento y devuelve el
    último frame leído (numpy array BGR). Bloqueante: llamar vía
    asyncio.to_thread."""

    cap = _open_camera()
    try:
        frame = None
        for _ in range(max(warmup_frames, 1)):
            ok, frame = cap.read()
            if not ok:
                raise CameraError(
                    "La cámara se abrió pero no devolvió fotogramas "
                    "(¿en uso por otro proceso?)."
                )
        return frame
    finally:
        cap.release()


def _encode_jpeg(frame) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise CameraError("No se pudo codificar la imagen capturada.")
    return buffer.tobytes()


def _capture_jpeg_sync() -> bytes:
    return _encode_jpeg(_read_frame_sync(WARMUP_FRAMES))


async def capture_jpeg() -> bytes:
    async with camera_lock:
        return await asyncio.to_thread(_capture_jpeg_sync)


def _check_dog_sync():
    """Captura un frame (calentamiento reducido) y busca un perro.

    Devuelve (encontrado, confianza, jpeg_bytes_o_None). Solo codifica a
    JPEG si se encontró un perro, para no gastar CPU en cada comprobación
    negativa.
    """
    frame = _read_frame_sync(DOG_CHECK_WARMUP_FRAMES)
    found, confidence = detection.find_dog(_net, frame, DOG_MIN_CONFIDENCE)
    jpeg_bytes = _encode_jpeg(frame) if found else None
    return found, confidence, jpeg_bytes


# --------------------------------------------------------------------------
# Vigilancia de perro (job periódico)
# --------------------------------------------------------------------------

def load_detector():
    if not (os.path.isfile(MODEL_PROTOTXT) and os.path.isfile(MODEL_WEIGHTS)):
        logger.warning(
            "No se encontraron los archivos del modelo de detección en %s. "
            "La vigilancia de perro estará desactivada hasta que los añadas "
            "(ver README, sección 'Detección automática de perro').",
            MODEL_DIR,
        )
        return None
    try:
        net = detection.load_net(MODEL_PROTOTXT, MODEL_WEIGHTS)
        logger.info("Modelo de detección cargado desde %s", MODEL_DIR)
        return net
    except Exception:
        logger.exception("No se pudo cargar el modelo de detección de perro")
        return None


async def watchdog_job(context: ContextTypes.DEFAULT_TYPE):
    if _net is None:
        return

    async with camera_lock:
        try:
            found, confidence, jpeg_bytes = await asyncio.to_thread(_check_dog_sync)
        except CameraError as exc:
            logger.warning("Vigilancia: no se pudo leer la cámara (%s)", exc)
            return
        except Exception:
            logger.exception("Vigilancia: error inesperado durante la comprobación")
            return

    if not found or jpeg_bytes is None:
        return

    now = time.monotonic()
    last = context.application.bot_data.get("last_dog_alert_ts", 0.0)
    if now - last < DOG_ALERT_COOLDOWN_SECONDS:
        logger.info(
            "Perro detectado (confianza %.0f%%) pero en cooldown, no se avisa",
            confidence * 100,
        )
        return
    context.application.bot_data["last_dog_alert_ts"] = now

    logger.info("¡Perro detectado! confianza=%.0f%%", confidence * 100)
    for user_id in ALLOWED_USER_IDS:
        try:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=jpeg_bytes,
                caption=f"🐶 ¡Perro detectado! (confianza {confidence:.0%})",
            )
        except Exception:
            logger.exception("No se pudo enviar la alerta de perro a user_id=%s", user_id)


def _watchdog_job_ref(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data.get("watchdog_job")


def _watchdog_status_text(job) -> str:
    if _net is None:
        return (
            "🚫 La vigilancia no está disponible: faltan los archivos del "
            "modelo de detección (ver README, sección 'Detección automática "
            "de perro')."
        )
    estado = "🟢 activada" if job.enabled else "🔴 desactivada"
    return (
        f"Vigilancia de perro: {estado}\n"
        f"Revisa la cámara cada {DOG_CHECK_INTERVAL_SECONDS:.0f}s "
        f"(aviso máx. cada {DOG_ALERT_COOLDOWN_SECONDS:.0f}s)."
    )


def _watchdog_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("🟢 Activar", callback_data="wd:on"),
            InlineKeyboardButton("🔴 Desactivar", callback_data="wd:off"),
        ]]
    )


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------

@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Bot de webcam listo.\n\n"
        f"Pulsa «{BUTTON_PHOTO}» o usa /foto para capturar una imagen.\n"
        f"Pulsa «{BUTTON_WATCHDOG}» o usa /vigilancia para la vigilancia "
        "automática de perro.",
        f"Pulsa «{BUTTON_RESET}» o usa /reset_cam si la cámara se queda ",
        "colgada y no responde.",
        reply_markup=MAIN_KEYBOARD,
    )


@restricted
async def cmd_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.UPLOAD_PHOTO)

    try:
        jpeg_bytes = await capture_jpeg()
    except CameraError as exc:
        logger.error("Fallo de cámara: %s", exc)
        await update.message.reply_text(f"⚠️ {exc}")
        return
    except Exception:
        logger.exception("Error inesperado capturando la foto")
        await update.message.reply_text(
            "⚠️ Error inesperado al capturar la foto. Revisa los logs del contenedor."
        )
        return

    await update.message.reply_photo(
        photo=jpeg_bytes,
        caption="📸 Captura de la webcam",
        reply_markup=MAIN_KEYBOARD,
    )
    logger.info("Foto enviada a user_id=%s", update.effective_user.id)


@restricted
async def cmd_vigilancia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    job = _watchdog_job_ref(context)
    if job is None:
        await update.message.reply_text(_watchdog_status_text(None))
        return
    await update.message.reply_text(
        _watchdog_status_text(job), reply_markup=_watchdog_keyboard()
    )


async def on_watchdog_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user

    if not _is_authorized(user):
        await query.answer("⛔ No tienes permiso.", show_alert=True)
        return

    job = _watchdog_job_ref(context)
    if job is None:
        await query.answer()
        return

    if query.data == "wd:on":
        job.enabled = True
    elif query.data == "wd:off":
        job.enabled = False

    await query.answer()
    await query.edit_message_text(
        _watchdog_status_text(job), reply_markup=_watchdog_keyboard()
    )


async def cmd_reset_cam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text("🔁 Reiniciando la cámara (reset USB)...")
    await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)

    async with camera_lock:
        try:
            node = await asyncio.to_thread(usb_reset.reset_usb_camera, CAMERA_DEVICE)
        except usb_reset.USBResetError as exc:
            logger.error("Reset USB fallido: %s", exc)
            await update.message.reply_text(f"⚠️ No se pudo resetear la cámara: {exc}")
            return
        except Exception:
            logger.exception("Error inesperado en el reset USB")
            await update.message.reply_text(
                "⚠️ Error inesperado al resetear la cámara. Revisa los logs "
                "del contenedor."
            )
            return

    logger.info("Cámara reseteada vía USB (%s)", node)
    await asyncio.sleep(RESET_SETTLE_SECONDS)

    # Verificación automática: intenta capturar una foto para confirmar
    # que la cámara ha vuelto a responder.
    try:
        jpeg_bytes = await capture_jpeg()
    except CameraError as exc:
        await update.message.reply_text(
            f"🔁 Reset USB realizado ({node}), pero la cámara aún no "
            f"responde ({exc}). Puede necesitar unos segundos más — "
            f"prueba «{BUTTON_PHOTO}» en breve."
        )
        return
    except Exception:
        logger.exception("Error inesperado verificando la cámara tras el reset")
        await update.message.reply_text(
            f"🔁 Reset USB realizado ({node}), pero no se pudo verificar "
            f"automáticamente. Prueba «{BUTTON_PHOTO}»."
        )
        return

    await update.message.reply_photo(
        photo=jpeg_bytes,
        caption="✅ Cámara reiniciada y respondiendo correctamente.",
        reply_markup=MAIN_KEYBOARD,
    )


@restricted
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Comandos disponibles:\n"
        "/foto — capturar y enviar una imagen de la webcam\n"
        "/vigilancia — ver/activar/desactivar el aviso automático al "
        "detectar un perro\n"
        "/reset_cam — reset USB de la cámara si se queda colgada\n"
        "/start — mostrar el teclado de botones\n"
        "/help — esta ayuda",
        reply_markup=MAIN_KEYBOARD,
    )


async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.message.text == BUTTON_PHOTO:
        await cmd_foto(update, context)
    elif update.message.text == BUTTON_WATCHDOG:
        await cmd_vigilancia(update, context)
    elif update.message.text == BUTTON_RESET:
        await cmd_reset_cam(update, context)


# --------------------------------------------------------------------------
# Arranque
# --------------------------------------------------------------------------

def build_app() -> Application:
    global _net

    if not BOT_TOKEN:
        raise SystemExit(
            "Falta TELEGRAM_BOT_TOKEN. Defínelo en el archivo .env (ver .env.example)."
        )
    if not ALLOWED_USER_IDS:
        logger.warning(
            "ALLOWED_USER_IDS está vacío: CUALQUIER usuario de Telegram podrá "
            "usar el bot, ver la webcam y recibir avisos de vigilancia. "
            "Configúralo en .env."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("foto", cmd_foto))
    app.add_handler(CommandHandler("vigilancia", cmd_vigilancia))
    app.add_handler(CommandHandler("reset_cam", cmd_reset_cam))
    app.add_handler(CallbackQueryHandler(on_watchdog_callback, pattern=r"^wd:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))

    _net = load_detector()
    if _net is not None:
        job = app.job_queue.run_repeating(
            watchdog_job,
            interval=DOG_CHECK_INTERVAL_SECONDS,
            first=DOG_CHECK_INTERVAL_SECONDS,
            name="dog_watchdog",
        )
        job.enabled = DOG_WATCHDOG_DEFAULT
        app.bot_data["watchdog_job"] = job
    else:
        app.bot_data["watchdog_job"] = None

    return app


def main():
    app = build_app()
    logger.info(
        "webcam-bot arrancando (device=%s, usuarios permitidos=%s, "
        "vigilancia=%s)",
        CAMERA_DEVICE,
        sorted(ALLOWED_USER_IDS) or "TODOS (sin restricción)",
        "disponible" if _net is not None else "no disponible (faltan pesos del modelo)",
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
