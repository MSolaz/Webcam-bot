"""
Handlers de Telegram: comandos, botones del teclado y callbacks inline.

Para añadir un comando nuevo: handler con @restricted, registro en
register_handlers(), entrada en cmd_help y cmd_start, y si tiene botón, la
constante BUTTON_*, su fila en MAIN_KEYBOARD y la rama en unknown_text.
"""

import asyncio
import logging

from telegram import ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from webcam_bot import usb_reset
from webcam_bot.auth import is_authorized, restricted
from webcam_bot.camera import CameraError
from webcam_bot.watchdog import watchdog_keyboard, watchdog_status_text

__all__ = ["MAIN_KEYBOARD", "register_handlers"]

logger = logging.getLogger("webcam-bot")

BUTTON_PHOTO = "📸 Hacer foto"
BUTTON_WATCHDOG = "🐶 Vigilancia"
BUTTON_RESET = "🔁 Reiniciar cámara"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[BUTTON_PHOTO], [BUTTON_WATCHDOG], [BUTTON_RESET]],
    resize_keyboard=True,
    is_persistent=True,
)


@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Bot de webcam listo.\n\n"
        f"Pulsa «{BUTTON_PHOTO}» o usa /foto para capturar una imagen.\n"
        f"Pulsa «{BUTTON_WATCHDOG}» o usa /vigilancia para la vigilancia "
        "automática de perro.\n"
        f"Pulsa «{BUTTON_RESET}» o usa /reset_cam si la cámara se queda "
        "colgada y no responde.",
        reply_markup=MAIN_KEYBOARD,
    )


@restricted
async def cmd_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = context.bot_data["settings"]
    camera = context.bot_data["camera"]
    chat = update.effective_chat
    await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.UPLOAD_PHOTO)

    try:
        jpeg_bytes = await camera.capture_jpeg(settings.warmup_frames)
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
    settings = context.bot_data["settings"]
    job = context.bot_data.get("watchdog_job")
    if job is None:
        await update.message.reply_text(watchdog_status_text(None, settings))
        return
    await update.message.reply_text(
        watchdog_status_text(job, settings), reply_markup=watchdog_keyboard()
    )


async def on_watchdog_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Los callbacks inline no llevan update.message, así que la autorización
    # se comprueba aquí a mano en vez de con @restricted.
    query = update.callback_query
    settings = context.bot_data["settings"]

    if not is_authorized(update.effective_user, settings.allowed_user_ids):
        await query.answer("⛔ No tienes permiso.", show_alert=True)
        return

    job = context.bot_data.get("watchdog_job")
    if job is None:
        await query.answer()
        return

    if query.data == "wd:on":
        job.enabled = True
    elif query.data == "wd:off":
        job.enabled = False

    await query.answer()
    await query.edit_message_text(
        watchdog_status_text(job, settings), reply_markup=watchdog_keyboard()
    )


@restricted
async def cmd_reset_cam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = context.bot_data["settings"]
    camera = context.bot_data["camera"]
    chat = update.effective_chat
    await update.message.reply_text("🔁 Reiniciando la cámara (reset USB)...")
    await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)

    async with camera.lock:
        try:
            node = await asyncio.to_thread(usb_reset.reset_usb_camera, camera.device)
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
    await asyncio.sleep(settings.reset_settle_seconds)

    # Verificación automática: intenta capturar una foto para confirmar
    # que la cámara ha vuelto a responder.
    try:
        jpeg_bytes = await camera.capture_jpeg(settings.warmup_frames)
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


def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("foto", cmd_foto))
    app.add_handler(CommandHandler("vigilancia", cmd_vigilancia))
    app.add_handler(CommandHandler("reset_cam", cmd_reset_cam))
    app.add_handler(CallbackQueryHandler(on_watchdog_callback, pattern=r"^wd:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))
