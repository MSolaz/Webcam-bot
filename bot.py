"""
webcam-bot
----------
Bot de Telegram que controla una webcam conectada al servidor y envía
una foto capturada al pulsar el botón "📸 Hacer foto" (o el comando /foto).

Pensado para desplegarse en Docker en el mismo servidor Linux donde está
conectada la webcam (ver docker-compose.yml para el mapeo del dispositivo).
"""

import asyncio
import logging
import os
import sys
from functools import wraps

import cv2
from telegram import ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

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

BUTTON_PHOTO = "📸 Hacer foto"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("webcam-bot")

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[BUTTON_PHOTO]], resize_keyboard=True, is_persistent=True
)


# --------------------------------------------------------------------------
# Autorización
# --------------------------------------------------------------------------

def restricted(handler):
    """Rechaza silenciosamente (con aviso) a usuarios no autorizados."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or (ALLOWED_USER_IDS and user.id not in ALLOWED_USER_IDS):
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


def _capture_jpeg_sync() -> bytes:
    """Abre la webcam, descarta fotogramas de calentamiento, captura uno y
    lo devuelve codificado en JPEG. Se ejecuta en un hilo aparte porque
    OpenCV es bloqueante."""

    cap = cv2.VideoCapture(CAMERA_DEVICE)
    if not cap.isOpened():
        raise CameraError(
            f"No se pudo abrir el dispositivo de cámara '{CAMERA_DEVICE}'. "
            "¿Está conectada y mapeada al contenedor?"
        )

    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

        frame = None
        for _ in range(max(WARMUP_FRAMES, 1)):
            ok, frame = cap.read()
            if not ok:
                raise CameraError(
                    "La cámara se abrió pero no devolvió fotogramas "
                    "(¿en uso por otro proceso?)."
                )

        ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise CameraError("No se pudo codificar la imagen capturada.")

        return buffer.tobytes()
    finally:
        cap.release()


async def capture_jpeg() -> bytes:
    return await asyncio.to_thread(_capture_jpeg_sync)


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------

@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Bot de webcam listo.\n\n"
        f"Pulsa «{BUTTON_PHOTO}» o usa /foto para capturar una imagen.",
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
    logger.info(
        "Foto enviada a user_id=%s", update.effective_user.id
    )


@restricted
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Comandos disponibles:\n"
        "/foto — capturar y enviar una imagen de la webcam\n"
        "/start — mostrar el teclado de botones\n"
        "/help — esta ayuda",
        reply_markup=MAIN_KEYBOARD,
    )


async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == BUTTON_PHOTO:
        await cmd_foto(update, context)


# --------------------------------------------------------------------------
# Arranque
# --------------------------------------------------------------------------

def build_app() -> Application:
    if not BOT_TOKEN:
        raise SystemExit(
            "Falta TELEGRAM_BOT_TOKEN. Defínelo en el archivo .env (ver .env.example)."
        )
    if not ALLOWED_USER_IDS:
        logger.warning(
            "ALLOWED_USER_IDS está vacío: CUALQUIER usuario de Telegram podrá "
            "usar el bot y ver la webcam. Configúralo en .env."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("foto", cmd_foto))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))

    return app


def main():
    app = build_app()
    logger.info(
        "webcam-bot arrancando (device=%s, usuarios permitidos=%s)",
        CAMERA_DEVICE,
        sorted(ALLOWED_USER_IDS) or "TODOS (sin restricción)",
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
