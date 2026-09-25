import asyncio
import contextlib
import io
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from webcam_bot import audio, diagnostics
from webcam_bot.camera import CameraError
from webcam_bot.config import Settings

SR = audio.SAMPLE_RATE
rng = np.random.default_rng(0)


def _ruido(segundos, nivel=0.01):
    return (rng.standard_normal(int(segundos * SR)) * nivel).astype(np.float32)


def _tono(segundos, hz=1000.0, amplitud=0.3):
    t = np.arange(int(segundos * SR)) / SR
    return (amplitud * np.sin(2 * np.pi * hz * t)).astype(np.float32)


# --- Análisis de audio ---

def test_level_dbfs():
    assert diagnostics.level_dbfs(np.zeros(SR, dtype=np.float32)) < -100
    assert diagnostics.level_dbfs(_tono(1, amplitud=1.0)) == pytest.approx(-3, abs=0.1)
    assert diagnostics.level_dbfs(np.zeros(0, dtype=np.float32)) < -100


def test_tone_amplitude_does_not_depend_on_duration():
    assert diagnostics.tone_amplitude(_tono(1), 1000) == pytest.approx(0.3, rel=0.02)
    assert diagnostics.tone_amplitude(_tono(3), 1000) == pytest.approx(0.3, rel=0.02)
    assert diagnostics.tone_amplitude(_tono(1, hz=440), 1000) < 0.01


def test_beep_heard_over_background_noise():
    fondo = _ruido(3)
    assert diagnostics.beep_heard(_ruido(2) + _tono(2, amplitud=0.02), fondo)
    assert not diagnostics.beep_heard(_ruido(2), fondo)
    # Silencio digital total: ni siquiera el "pitido" cuenta si es ~0
    assert not diagnostics.beep_heard(_tono(2, amplitud=1e-6), np.zeros(SR, np.float32))


def test_beep_and_wav():
    pitido = audio.beep(1000, 1.0)
    assert len(pitido) == SR
    assert abs(pitido[0]) < 0.01  # sin chasquido al empezar
    with wave.open(io.BytesIO(audio.to_wav_bytes(pitido))) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (SR, 1, 2)
        assert wav.getnframes() == SR


def test_microphone_keeps_recent_audio():
    mic = audio.Microphone("default", window=15600, hop=7680, on_window=lambda w: None)
    assert not mic.is_receiving()
    assert len(mic.recent_audio(3)) == 0
    for i in range(10):
        mic._recent.append(np.full(7680, i, dtype=np.float32))
    reciente = mic.recent_audio(1.0)
    assert len(reciente) == SR
    assert reciente[-1] == 9


# --- Diagnóstico completo con dispositivos falsos ---

class FakeCamera:
    def __init__(self, error=None):
        self.error = error

    async def capture_jpeg(self, warmup_frames):
        if self.error:
            raise CameraError(self.error)
        return b"jpeg"


class FakeMicrophone:
    device = "plughw:CARD=PCH,DEV=0"

    def __init__(self, nivel=0.01, eco=0.05):
        self.nivel = nivel
        self.eco = eco
        self.sono_pitido = False

    def is_receiving(self):
        return True

    def recent_audio(self, segundos):
        senal = _ruido(segundos, self.nivel)
        if self.sono_pitido:
            senal = senal + _tono(segundos, amplitud=self.eco)
        return senal


class FakeGuard:
    def __init__(self, microphone):
        self.microphone = microphone
        self.enabled = True
        self.threshold = 0.5
        self.pausado = False

    @contextlib.contextmanager
    def paused(self):
        self.pausado = True
        yield
        self.pausado = False


@pytest.fixture
def entorno(monkeypatch):
    monkeypatch.setattr(diagnostics, "_MIC_LATENCY_SECONDS", 0)
    mic = FakeMicrophone()
    guard = FakeGuard(mic)
    reproducido = []

    def play_sound(path, device):
        reproducido.append((path, device, guard.pausado))
        mic.sono_pitido = True

    monkeypatch.setattr(audio, "play_sound", play_sound)
    bot_data = {
        "settings": Settings.from_env({"AUDIO_OUTPUT_DEVICE": "plughw:CARD=PCH,DEV=0"}),
        "camera": FakeCamera(),
        "net": object(),
        "bark_guard": guard,
    }
    return bot_data, mic, reproducido


def _texto(bot_data):
    return asyncio.run(diagnostics.run_diagnostics(bot_data))


def test_everything_ok(entorno):
    bot_data, _, reproducido = entorno
    resultado = _texto(bot_data)

    assert resultado.photo == b"jpeg"
    assert resultado.recording.startswith(b"RIFF")
    assert "Cámara: ✅" in resultado.text
    assert "Micrófono: ✅" in resultado.text
    assert "Altavoz: ✅" in resultado.text
    assert "lo ha captado ✅" in resultado.text
    assert "perro ✅" in resultado.text and "ladridos ✅" in resultado.text
    # El pitido suena con el anti-ladridos en pausa, por el altavoz configurado
    assert reproducido[0][1:] == ("plughw:CARD=PCH,DEV=0", True)


def test_silent_microphone(entorno):
    bot_data, mic, _ = entorno
    mic.nivel = 0.0
    mic.eco = 0.0

    texto = _texto(bot_data).text

    assert "Micrófono: ⚠️ no llega sonido" in texto
    assert "no lo ha captado ⚠️" in texto


def test_beep_not_heard(entorno):
    bot_data, mic, _ = entorno
    mic.eco = 0.0

    texto = _texto(bot_data).text

    assert "Altavoz: ✅" in texto
    assert "no lo ha captado ⚠️" in texto


def test_speaker_and_camera_errors(entorno, monkeypatch):
    bot_data, _, _ = entorno
    bot_data["camera"] = FakeCamera(error="cámara colgada")

    def falla(path, device):
        raise audio.AudioError("audio open error")

    monkeypatch.setattr(audio, "play_sound", falla)

    resultado = _texto(bot_data)

    assert resultado.photo is None
    assert "Cámara: ❌ cámara colgada" in resultado.text
    assert "Altavoz: ❌ audio open error" in resultado.text
    assert "Micrófono: ✅" in resultado.text


def test_without_bark_guard_records_with_arecord(entorno, monkeypatch):
    bot_data, _, _ = entorno
    bot_data["bark_guard"] = None
    bot_data["net"] = None
    grabaciones = []

    def record(device, segundos):
        grabaciones.append(device)
        return _ruido(segundos) + (_tono(segundos, amplitud=0.05) if len(grabaciones) > 1 else 0)

    monkeypatch.setattr(audio, "record", record)

    texto = _texto(bot_data).text

    assert len(grabaciones) == 2  # nivel del micrófono + prueba de eco
    assert "lo ha captado ✅" in texto
    assert "perro ❌" in texto and "ladridos ❌ no disponible" in texto
