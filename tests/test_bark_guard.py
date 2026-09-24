"""Flujo del anti-ladridos con cámara, detector, altavoz y Telegram falsos."""

import asyncio

import numpy as np
import pytest

from webcam_bot import audio, bark_guard, detection
from webcam_bot.config import Settings


class FakeDetector:
    window_samples = 15600
    threshold = 0.5

    def probability(self, window):
        return 0.9


class FakeCamera:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.device = "/dev/video0"

    def read_frame_sync(self, warmup_frames):
        return np.zeros((10, 10, 3), dtype=np.uint8)


class FakeBot:
    def __init__(self):
        self.photos = []
        self.messages = []

    async def send_photo(self, chat_id, photo, caption):
        self.photos.append((chat_id, caption))

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


@pytest.fixture
def entorno(monkeypatch):
    """Devuelve (guard, bot, reproducidos, fotos_con_perro) listos para usar."""
    monkeypatch.setattr(bark_guard, "_CAMERA_CHECK_INTERVAL_SECONDS", 0)
    reproducidos = []
    monkeypatch.setattr(audio, "play_sound", lambda path, device: reproducidos.append(path))

    # Qué devuelve el detector de perro en cada foto sucesiva
    fotos_con_perro = []
    monkeypatch.setattr(
        detection, "find_dog",
        lambda net, frame, c: (True, 0.8) if fotos_con_perro.pop(0) else (False, 0.0),
    )

    settings = Settings.from_env({"ALLOWED_USER_IDS": "1,2", "BARK_CAMERA_CHECKS": "3"})
    guard = bark_guard.BarkGuard(settings, FakeCamera(), FakeDetector(), net=object())
    bot = FakeBot()
    guard._bot = bot
    return guard, bot, reproducidos, fotos_con_perro


def test_dog_in_view_plays_sound_and_sends_photo(entorno):
    guard, bot, reproducidos, fotos_con_perro = entorno
    fotos_con_perro += [False, True]  # lo ve en la segunda foto

    asyncio.run(guard.handle_bark(0.9))

    assert reproducidos == [guard.settings.bark_sound_file]
    assert sorted(uid for uid, _ in bot.photos) == [1, 2]
    assert all("reproduciendo el audio" in caption for _, caption in bot.photos)
    assert fotos_con_perro == []


def test_no_dog_only_notifies(entorno):
    guard, bot, reproducidos, fotos_con_perro = entorno
    fotos_con_perro += [False, False, False]

    asyncio.run(guard.handle_bark(0.9))

    assert reproducidos == []
    assert all("no veo ningún perro" in caption for _, caption in bot.photos)
    assert len(bot.photos) == 2


def test_cooldown_between_actions(entorno):
    guard, bot, reproducidos, fotos_con_perro = entorno
    fotos_con_perro += [True, True]

    async def dos_ladridos():
        await guard.handle_bark(0.9)
        await guard.handle_bark(0.9)

    asyncio.run(dos_ladridos())

    assert len(reproducidos) == 1
    assert fotos_con_perro == [True]  # la segunda vez ni siquiera mira la cámara


def test_sound_error_is_reported(entorno, monkeypatch):
    guard, bot, reproducidos, fotos_con_perro = entorno
    fotos_con_perro += [True]

    def falla(path, device):
        raise audio.AudioError("altavoz desconectado")

    monkeypatch.setattr(audio, "play_sound", falla)

    asyncio.run(guard.handle_bark(0.9))

    assert all("altavoz desconectado" in caption for _, caption in bot.photos)


def test_camera_error_sends_text_without_photo(entorno, monkeypatch):
    guard, bot, reproducidos, _ = entorno

    def sin_camara(warmup_frames):
        raise bark_guard.CameraError("cámara colgada")

    monkeypatch.setattr(guard._camera, "read_frame_sync", sin_camara)

    asyncio.run(guard.handle_bark(0.9))

    assert reproducidos == []
    assert bot.photos == []
    assert all("cámara colgada" in text for _, text in bot.messages)
