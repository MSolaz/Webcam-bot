"""Punto de entrada: `python -m webcam_bot`."""

import logging

from telegram import Update

from webcam_bot.app import build_app
from webcam_bot.config import Settings, setup_logging

logger = logging.getLogger("webcam-bot")


def main():
    setup_logging()
    settings = Settings.from_env()
    app = build_app(settings)
    logger.info(
        "webcam-bot arrancando (device=%s, usuarios permitidos=%s, "
        "vigilancia=%s)",
        settings.camera_device,
        sorted(settings.allowed_user_ids) or "TODOS (sin restricción)",
        "disponible"
        if app.bot_data["net"] is not None
        else "no disponible (faltan pesos del modelo)",
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
