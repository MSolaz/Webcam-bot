"""
Vigilancia de perro: job periódico que revisa la cámara y avisa por
Telegram a los usuarios autorizados cuando detecta un perro.

Estado compartido en context.bot_data:
- "net": red de detección cargada (None si faltan los pesos).
- "watchdog_job": el Job de la JobQueue (None si no hay vigilancia).
- "last_dog_alert_ts": instante (time.monotonic) de la última alerta.
"""

import asyncio
import logging
import os
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from webcam_bot import detection
from webcam_bot.camera import Camera, CameraError, encode_jpeg
from webcam_bot.config import Settings

__all__ = [
    "load_detector",
    "watchdog_job",
    "watchdog_keyboard",
    "watchdog_status_text",
]

logger = logging.getLogger("webcam-bot")


def load_detector(settings: Settings):
    """Carga la red de detección. Devuelve None (y lo registra en el log) si
    faltan los archivos del modelo o no se pueden cargar."""
    if not (
        os.path.isfile(settings.model_prototxt)
        and os.path.isfile(settings.model_weights)
    ):
        logger.warning(
            "No se encontraron los archivos del modelo de detección en %s. "
            "La vigilancia de perro estará desactivada hasta que los añadas "
            "(ver README, sección 'Detección automática de perro').",
            settings.model_dir,
        )
        return None
    try:
        net = detection.load_net(settings.model_prototxt, settings.model_weights)
        logger.info("Modelo de detección cargado desde %s", settings.model_dir)
        return net
    except Exception:
        logger.exception("No se pudo cargar el modelo de detección de perro")
        return None


def _check_dog_sync(camera: Camera, net, settings: Settings):
    """Captura un frame (calentamiento reducido) y busca un perro.

    Devuelve (encontrado, confianza, jpeg_bytes_o_None). Solo codifica a
    JPEG si se encontró un perro, para no gastar CPU en cada comprobación
    negativa.
    """
    frame = camera.read_frame_sync(settings.dog_check_warmup_frames)
    found, confidence = detection.find_dog(net, frame, settings.dog_min_confidence)
    jpeg_bytes = encode_jpeg(frame) if found else None
    return found, confidence, jpeg_bytes


async def watchdog_job(context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.application.bot_data
    net = bot_data.get("net")
    if net is None:
        return

    settings: Settings = bot_data["settings"]
    camera: Camera = bot_data["camera"]

    async with camera.lock:
        try:
            found, confidence, jpeg_bytes = await asyncio.to_thread(
                _check_dog_sync, camera, net, settings
            )
        except CameraError as exc:
            logger.warning("Vigilancia: no se pudo leer la cámara (%s)", exc)
            return
        except Exception:
            logger.exception("Vigilancia: error inesperado durante la comprobación")
            return

    if not found or jpeg_bytes is None:
        return

    now = time.monotonic()
    last = bot_data.get("last_dog_alert_ts", 0.0)
    if now - last < settings.dog_alert_cooldown_seconds:
        logger.info(
            "Perro detectado (confianza %.0f%%) pero en cooldown, no se avisa",
            confidence * 100,
        )
        return
    bot_data["last_dog_alert_ts"] = now

    logger.info("¡Perro detectado! confianza=%.0f%%", confidence * 100)
    for user_id in settings.allowed_user_ids:
        try:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=jpeg_bytes,
                caption=f"🐶 ¡Perro detectado! (confianza {confidence:.0%})",
            )
        except Exception:
            logger.exception("No se pudo enviar la alerta de perro a user_id=%s", user_id)


def watchdog_status_text(job, settings: Settings) -> str:
    if job is None:
        return (
            "🚫 La vigilancia no está disponible: faltan los archivos del "
            "modelo de detección (ver README, sección 'Detección automática "
            "de perro')."
        )
    estado = "🟢 activada" if job.enabled else "🔴 desactivada"
    return (
        f"Vigilancia de perro: {estado}\n"
        f"Revisa la cámara cada {settings.dog_check_interval_seconds:.0f}s "
        f"(aviso máx. cada {settings.dog_alert_cooldown_seconds:.0f}s)."
    )


def watchdog_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("🟢 Activar", callback_data="wd:on"),
            InlineKeyboardButton("🔴 Desactivar", callback_data="wd:off"),
        ]]
    )
