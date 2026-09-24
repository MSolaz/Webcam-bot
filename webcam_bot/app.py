"""
Construcción de la Application de Telegram: valida la configuración,
registra los handlers, carga el detector y programa la vigilancia.
"""

import logging

from telegram.ext import Application

from webcam_bot.bark_guard import BarkGuard, load_bark_detector
from webcam_bot.camera import Camera
from webcam_bot.config import Settings
from webcam_bot.handlers import register_handlers
from webcam_bot.watchdog import load_detector, watchdog_job

__all__ = ["build_app"]

logger = logging.getLogger("webcam-bot")


def build_app(settings: Settings) -> Application:
    if not settings.bot_token:
        raise SystemExit(
            "Falta TELEGRAM_BOT_TOKEN. Defínelo en el archivo .env (ver .env.example)."
        )
    if not settings.allowed_user_ids:
        logger.warning(
            "ALLOWED_USER_IDS está vacío: CUALQUIER usuario de Telegram podrá "
            "usar el bot, ver la webcam y recibir avisos de vigilancia. "
            "Configúralo en .env."
        )

    app = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data["settings"] = settings
    app.bot_data["camera"] = Camera(
        settings.camera_device, settings.camera_width, settings.camera_height
    )

    register_handlers(app)

    net = load_detector(settings)
    if net is not None and app.job_queue is None:
        logger.error(
            "Hay modelo de detección pero no hay JobQueue disponible: "
            "falta el extra 'job-queue' de python-telegram-bot "
            "(python-telegram-bot[job-queue] en requirements.txt). "
            "La vigilancia automática queda desactivada."
        )
        net = None
    app.bot_data["net"] = net

    if net is not None:
        job = app.job_queue.run_repeating(
            watchdog_job,
            interval=settings.dog_check_interval_seconds,
            first=settings.dog_check_interval_seconds,
            name="dog_watchdog",
        )
        job.enabled = settings.dog_watchdog_enabled
        app.bot_data["watchdog_job"] = job
    else:
        app.bot_data["watchdog_job"] = None

    app.bot_data["bark_guard"] = _build_bark_guard(settings, app.bot_data["camera"], net)

    return app


def _build_bark_guard(settings: Settings, camera: Camera, net):
    """El anti-ladridos necesita el modelo de ladridos y el detector de perro
    (para comprobar con la cámara). Sin alguno de los dos, queda desactivado."""
    bark_detector = load_bark_detector(settings)
    if bark_detector is None:
        return None
    if net is None:
        logger.warning(
            "Hay modelo de ladridos pero no detector de perro: el anti-ladridos "
            "queda desactivado porque no podría comprobar con la cámara."
        )
        return None
    return BarkGuard(settings, camera, bark_detector, net)


async def _post_init(app: Application):
    guard = app.bot_data.get("bark_guard")
    if guard is not None:
        await guard.start(app.bot)


async def _post_shutdown(app: Application):
    guard = app.bot_data.get("bark_guard")
    if guard is not None:
        await guard.stop()
