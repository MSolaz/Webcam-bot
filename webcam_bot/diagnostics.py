"""
Diagnóstico (/diagnostico): comprueba que la cámara, el micrófono y el
altavoz funcionan y que los modelos están cargados.

- Cámara: hace una foto.
- Micrófono: toma 3 s de audio y mide su volumen. Si el anti-ladridos está
  en marcha, el micrófono ya está abierto y se usa su audio reciente (ALSA no
  deja abrirlo dos veces); si no, se graba aparte con arecord.
- Altavoz: reproduce un pitido de 1000 Hz y comprueba si el micrófono lo
  capta (prueba de eco). Si lo capta, altavoz y micrófono funcionan; si no,
  puede que solo estén lejos o con el volumen bajo, así que se pregunta al
  usuario si lo ha oído.
"""

import asyncio
import os
import tempfile
from dataclasses import dataclass, field

import numpy as np

from webcam_bot import audio
from webcam_bot.camera import CameraError

__all__ = ["Diagnosis", "beep_heard", "level_dbfs", "run_diagnostics", "tone_amplitude"]

_MIC_SECONDS = 3.0
_BEEP_HZ = 1000.0
_BEEP_SECONDS = 1.0
# Por debajo de este volumen se considera que no llega sonido
_SILENCE_DBFS = -70.0
# El pitido se considera captado si en su frecuencia hay al menos 4 veces
# (12 dB) más señal que en el audio normal, y no es prácticamente cero
_ECHO_RATIO = 4.0
_ECHO_MIN_AMPLITUDE = 1e-4
# El Microphone entrega el audio en bloques de ~0,5 s: margen para que el
# final del pitido ya esté en su búfer
_MIC_LATENCY_SECONDS = 0.6


def level_dbfs(samples: np.ndarray) -> float:
    """Volumen medio (RMS) en dBFS: 0 es el máximo, -90 es prácticamente
    silencio digital."""
    if len(samples) == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    return 20 * np.log10(max(rms, 1e-6))


def tone_amplitude(samples: np.ndarray, frequency: float) -> float:
    """Amplitud aproximada de la componente de `frequency` Hz (misma escala
    que la señal), independiente de la duración del audio."""
    n = len(samples)
    if n == 0:
        return 0.0
    t = np.arange(n) / audio.SAMPLE_RATE
    window = np.hanning(n)
    component = np.sum(samples * window * np.exp(-2j * np.pi * frequency * t))
    return float(2 * abs(component) / np.sum(window))


def beep_heard(during: np.ndarray, baseline: np.ndarray) -> bool:
    heard = tone_amplitude(during, _BEEP_HZ)
    normal = tone_amplitude(baseline, _BEEP_HZ)
    return heard >= _ECHO_MIN_AMPLITUDE and heard >= _ECHO_RATIO * normal


@dataclass
class Diagnosis:
    lines: list = field(default_factory=list)
    photo: bytes | None = None
    recording: bytes | None = None  # WAV con lo que oye el micrófono

    @property
    def text(self) -> str:
        return "🩺 Diagnóstico\n" + "\n".join(self.lines)


async def run_diagnostics(bot_data) -> Diagnosis:
    settings = bot_data["settings"]
    guard = bot_data.get("bark_guard")
    result = Diagnosis()

    # --- Cámara ---
    try:
        result.photo = await bot_data["camera"].capture_jpeg(settings.warmup_frames)
        result.lines.append("📷 Cámara: ✅ responde (foto adjunta)")
    except CameraError as exc:
        result.lines.append(f"📷 Cámara: ❌ {exc}")

    # --- Micrófono ---
    baseline = None
    try:
        baseline = await _mic_sample(guard, settings)
        result.recording = audio.to_wav_bytes(baseline)
        nivel = level_dbfs(baseline)
        if nivel < _SILENCE_DBFS:
            result.lines.append(
                "🎤 Micrófono: ⚠️ no llega sonido (silencio total). ¿Está "
                "silenciado o es otro micrófono? (ver README, sección 7)"
            )
        else:
            result.lines.append(
                f"🎤 Micrófono: ✅ recibe sonido (nivel {nivel:.0f} dB; 0 es "
                "el máximo). Escucha la grabación adjunta."
            )
    except audio.AudioError as exc:
        result.lines.append(f"🎤 Micrófono: ❌ {exc}")

    # --- Altavoz (+ prueba de eco con el micrófono) ---
    try:
        during = await _play_beep_and_listen(guard, settings, listen=baseline is not None)
        result.lines.append("🔊 Altavoz: ✅ pitido reproducido. ¿Lo has oído?")
        if during is not None:
            if beep_heard(during, baseline):
                result.lines.append("    🎤 El micrófono lo ha captado ✅")
            else:
                result.lines.append(
                    "    🎤 El micrófono no lo ha captado ⚠️ (pueden estar "
                    "lejos, o el volumen del altavoz o del micrófono es bajo)"
                )
    except audio.AudioError as exc:
        result.lines.append(f"🔊 Altavoz: ❌ {exc}")

    # --- Modelos ---
    perro = "✅" if bot_data.get("net") is not None else "❌ faltan los pesos"
    if guard is not None:
        estado = "activado" if guard.enabled else "desactivado"
        ladridos = f"✅ (umbral {guard.threshold:.0%}, {estado})"
    else:
        ladridos = "❌ no disponible"
    result.lines.append(f"🧠 Modelos: perro {perro} · ladridos {ladridos}")

    return result


async def _mic_sample(guard, settings) -> np.ndarray:
    if guard is not None:
        if not guard.microphone.is_receiving():
            raise audio.AudioError(
                f"no llega audio de '{guard.microphone.device}'. Revisa "
                "AUDIO_INPUT_DEVICE y los logs."
            )
        return guard.microphone.recent_audio(_MIC_SECONDS)
    return await asyncio.to_thread(audio.record, settings.audio_input_device, _MIC_SECONDS)


async def _play_beep_and_listen(guard, settings, listen: bool):
    """Reproduce el pitido. Si `listen`, devuelve el audio del micrófono
    mientras sonaba (o None si no se ha podido escuchar)."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio.to_wav_bytes(audio.beep(_BEEP_HZ, _BEEP_SECONDS)))
        beep_path = f.name
    play = asyncio.to_thread(audio.play_sound, beep_path, settings.audio_output_device)
    try:
        if guard is not None:
            with guard.paused():  # que el anti-ladridos no analice el pitido
                await play
                if not listen:
                    return None
                await asyncio.sleep(_MIC_LATENCY_SECONDS)
                return guard.microphone.recent_audio(_BEEP_SECONDS + 1.0)

        if not listen:
            await play
            return None
        # Sin anti-ladridos: grabar a la vez que suena el pitido
        grabacion = asyncio.create_task(
            asyncio.to_thread(audio.record, settings.audio_input_device, _BEEP_SECONDS + 2)
        )
        during = None
        try:
            await asyncio.sleep(0.5)
            await play
        finally:
            # Se espera a la grabación también si el pitido falla, para no
            # dejar la tarea suelta
            try:
                during = await grabacion
            except audio.AudioError:
                during = None
        return during
    finally:
        os.remove(beep_path)
