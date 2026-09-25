"""Botones inline de activar/desactivar (vigilancia y anti-ladridos)."""

import asyncio
import importlib.util
import sys
import types
from types import SimpleNamespace

import pytest

# handlers importa usb_reset, que usa fcntl (solo Linux). Estos tests no
# llegan a usarlo, así que en Windows basta con un módulo vacío mientras se
# importa (luego se quita, para que test_usb_reset se siga saltando).
_sin_fcntl = importlib.util.find_spec("fcntl") is None
if _sin_fcntl:
    sys.modules["fcntl"] = types.ModuleType("fcntl")

from webcam_bot import handlers  # noqa: E402
from webcam_bot.config import Settings  # noqa: E402

if _sin_fcntl:
    del sys.modules["fcntl"]


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append(text)


def _pulsar(callback, data, bot_data, user_id=1):
    query = FakeQuery(data)
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=user_id))
    asyncio.run(callback(update, SimpleNamespace(bot_data=bot_data)))
    return query


@pytest.fixture
def bot_data():
    guard = SimpleNamespace(
        enabled=True,
        threshold=0.5,
        settings=SimpleNamespace(bark_alert_cooldown_seconds=60),
    )
    return {
        "settings": Settings.from_env({"ALLOWED_USER_IDS": "1"}),
        "watchdog_job": SimpleNamespace(enabled=True),
        "bark_guard": guard,
    }


@pytest.mark.parametrize("callback, prefijo, clave", [
    (handlers.on_watchdog_callback, "wd", "watchdog_job"),
    (handlers.on_bark_guard_callback, "bk", "bark_guard"),
])
def test_toggle_changes_state_and_edits_message(bot_data, callback, prefijo, clave):
    query = _pulsar(callback, f"{prefijo}:off", bot_data)

    assert bot_data[clave].enabled is False
    assert len(query.edits) == 1
    assert "desactivad" in query.edits[0]


@pytest.mark.parametrize("callback, prefijo, clave", [
    (handlers.on_watchdog_callback, "wd", "watchdog_job"),
    (handlers.on_bark_guard_callback, "bk", "bark_guard"),
])
def test_same_state_does_not_edit_message(bot_data, callback, prefijo, clave):
    # Ya está activado: editar con el mismo texto daría "Message is not modified"
    query = _pulsar(callback, f"{prefijo}:on", bot_data)

    assert bot_data[clave].enabled is True
    assert query.edits == []
    assert query.answers[0].startswith("Ya estaba activad")


def test_unauthorized_user_cannot_toggle(bot_data):
    query = _pulsar(handlers.on_bark_guard_callback, "bk:off", bot_data, user_id=99)

    assert bot_data["bark_guard"].enabled is True
    assert query.edits == []
