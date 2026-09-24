"""
Autorización de usuarios de Telegram.

La lista de usuarios permitidos se lee de context.bot_data["settings"]
(ver webcam_bot.app.build_app).
"""

import logging
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes

__all__ = ["is_authorized", "restricted"]

logger = logging.getLogger("webcam-bot")


def is_authorized(user, allowed_user_ids) -> bool:
    """Vacío = cualquier usuario está autorizado."""
    return bool(user) and (not allowed_user_ids or user.id in allowed_user_ids)


def restricted(handler):
    """Rechaza silenciosamente (con aviso) a usuarios no autorizados."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        allowed = context.bot_data["settings"].allowed_user_ids
        if not is_authorized(user, allowed):
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
