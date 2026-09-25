"""
Anti-ladridos: escucha el micrófono y, al oír un ladrido, comprueba con la
cámara si hay un perro.

- Perro a la vista → reproduce el audio por el altavoz y avisa por Telegram
  con la foto.
- Sin perro → solo avisa por Telegram con la foto.

Entre dos actuaciones hay un tiempo mínimo (bark_alert_cooldown_seconds).
Mientras suena el audio (y un momento después) no se escucha, para que el
propio audio no dispare otra detección.

El BarkGuard se guarda en bot_data["bark_guard"] (None si no está
disponible) y se arranca/para con la Application (ver app.py).
"""

import asyncio
import contextlib
import logging
import os
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from webcam_bot import audio, detection
from webcam_bot.bark_detection import BarkDetector
from webcam_bot.camera import Camera, CameraError, encode_jpeg
from webcam_bot.config import Settings

__all__ = [
    "BarkGuard",
    "bark_guard_keyboard",
    "bark_guard_status_text",
    "load_bark_detector",
]

logger = logging.getLogger("webcam-bot")

# Ventanas solapadas cada 0,48 s, igual que en el entrenamiento
_HOP_SAMPLES = 7680
# Segundos que se ignora el micrófono tras actuar: la última ventana (~1 s)
# puede contener todavía el final del audio reproducido
_IGNORE_AFTER_ACTION_SECONDS = 1.5
_CAMERA_CHECK_INTERVAL_SECONDS = 1.0


def load_bark_detector(settings: Settings):
    """Carga el modelo de ladridos. Devuelve None (y lo registra en el log) si
    faltan los archivos o no se pueden cargar."""
    if not (
        os.path.isfile(settings.bark_model) and os.path.isfile(settings.bark_model_info)
    ):
        logger.warning(
            "No se encontraron ladridos.tflite y ladridos_info.json en %s. "
            "El anti-ladridos estará desactivado (ver README, sección "
            "'Anti-ladridos').",
            settings.model_dir,
        )
        return None
    try:
        detector = BarkDetector(
            settings.bark_model, settings.bark_model_info, settings.bark_threshold
        )
        logger.info(
            "Modelo de ladridos cargado desde %s (umbral %.2f)",
            settings.model_dir, detector.threshold,
        )
        return detector
    except Exception:
        logger.exception("No se pudo cargar el modelo de ladridos")
        return None


def _look_for_dog_sync(camera: Camera, net, settings: Settings):
    """Captura un frame y busca un perro. Devuelve (encontrado, confianza,
    jpeg). Bloqueante: llamar vía asyncio.to_thread con camera.lock."""
    frame = camera.read_frame_sync(settings.dog_check_warmup_frames)
    found, confidence = detection.find_dog(net, frame, settings.dog_min_confidence)
    return found, confidence, encode_jpeg(frame)


class BarkGuard:
    def __init__(self, settings: Settings, camera: Camera, detector: BarkDetector, net):
        self.settings = settings
        self.enabled = settings.bark_guard_enabled
        self._camera = camera
        self._detector = detector
        self._net = net
        self._bot = None
        self._loop = None
        self._task = None
        self._queue = asyncio.Queue(maxsize=8)
        self._last_action_ts = float("-inf")
        self._ignore_until = 0.0
        self._microphone = audio.Microphone(
            settings.audio_input_device,
            detector.window_samples,
            _HOP_SAMPLES,
            self._on_window,
        )

    @property
    def threshold(self) -> float:
        return self._detector.threshold

    @property
    def microphone(self) -> audio.Microphone:
        return self._microphone

    @contextlib.contextmanager
    def paused(self):
        """No analiza el micrófono mientras dure el bloque ni un momento
        después (para no reaccionar a lo que suena por el altavoz)."""
        self._ignore_until = float("inf")
        try:
            yield
        finally:
            self._ignore_until = time.monotonic() + _IGNORE_AFTER_ACTION_SECONDS

    # --- Arranque / parada (desde app.py) ---

    async def start(self, bot):
        self._bot = bot
        self._loop = asyncio.get_running_loop()
        if not os.path.isfile(self.settings.bark_sound_file):
            logger.warning(
                "No se encontró el audio anti-ladridos %s: se avisará por "
                "Telegram pero no sonará nada.",
                self.settings.bark_sound_file,
            )
        self._microphone.start()
        self._task = asyncio.create_task(self._run(), name="anti-ladridos")

    async def stop(self):
        self._microphone.stop()
        if self._task is not None:
            self._task.cancel()

    # --- Recepción de audio ---

    def _on_window(self, window):
        """Llamado desde el hilo del micrófono."""
        self._loop.call_soon_threadsafe(self._enqueue, window)

    def _enqueue(self, window):
        if self._queue.full():
            self._queue.get_nowait()  # descarta la ventana más antigua
        self._queue.put_nowait(window)

    async def _run(self):
        while True:
            window = await self._queue.get()
            if not self.enabled or time.monotonic() < self._ignore_until:
                continue
            try:
                probability = await asyncio.to_thread(self._detector.probability, window)
                if probability >= self._detector.threshold:
                    await self.handle_bark(probability)
            except Exception:
                logger.exception("Anti-ladridos: error inesperado procesando el audio")

    # --- Actuación ---

    async def handle_bark(self, probability: float):
        now = time.monotonic()
        if now - self._last_action_ts < self.settings.bark_alert_cooldown_seconds:
            logger.info(
                "Ladrido detectado (%.0f%%) pero en cooldown, no se actúa",
                probability * 100,
            )
            return
        self._last_action_ts = now
        logger.info("Ladrido detectado (%.0f%%): buscando al perro", probability * 100)

        try:
            found, confidence, jpeg = await self._look_for_dog()
        except CameraError as exc:
            logger.warning("Anti-ladridos: no se pudo leer la cámara (%s)", exc)
            await self._notify(
                None,
                f"👂 Oigo un ladrido ({probability:.0%}) pero no he podido usar "
                f"la cámara para comprobarlo: {exc}",
            )
            return

        if found:
            logger.info("Perro a la vista (%.0f%%): reproduciendo audio", confidence * 100)
            caption = (
                f"🔊 Ladrido detectado ({probability:.0%}) y perro a la vista "
                f"({confidence:.0%}): reproduciendo el audio."
            )
            error = await self._play_sound()
            if error:
                caption += f"\n⚠️ Pero no se pudo reproducir: {error}"
        else:
            logger.info("Ladrido detectado pero no se ve ningún perro")
            caption = (
                f"👂 Oigo un ladrido ({probability:.0%}) pero no veo ningún "
                "perro en la cámara."
            )
        await self._notify(jpeg, caption)

    async def _look_for_dog(self):
        """Hace hasta bark_camera_checks fotos (una por segundo) hasta ver un
        perro. Devuelve (encontrado, confianza, jpeg de la última foto)."""
        checks = max(self.settings.bark_camera_checks, 1)
        for i in range(checks):
            async with self._camera.lock:
                found, confidence, jpeg = await asyncio.to_thread(
                    _look_for_dog_sync, self._camera, self._net, self.settings
                )
            if found:
                return True, confidence, jpeg
            if i < checks - 1:
                await asyncio.sleep(_CAMERA_CHECK_INTERVAL_SECONDS)
        return False, 0.0, jpeg

    async def _play_sound(self):
        """Reproduce el audio sin escuchar mientras tanto. Devuelve el mensaje
        de error, o None si ha sonado bien."""
        with self.paused():
            try:
                await asyncio.to_thread(
                    audio.play_sound,
                    self.settings.bark_sound_file,
                    self.settings.audio_output_device,
                )
                return None
            except audio.AudioError as exc:
                logger.error("Anti-ladridos: %s", exc)
                return str(exc)

    async def _notify(self, jpeg, text: str):
        for user_id in self.settings.allowed_user_ids:
            try:
                if jpeg is not None:
                    await self._bot.send_photo(chat_id=user_id, photo=jpeg, caption=text)
                else:
                    await self._bot.send_message(chat_id=user_id, text=text)
            except Exception:
                logger.exception("No se pudo enviar el aviso de ladrido a user_id=%s", user_id)


def bark_guard_status_text(guard) -> str:
    if guard is None:
        return (
            "🚫 El anti-ladridos no está disponible: faltan el modelo de "
            "ladridos o el detector de perro (ver README, sección "
            "'Anti-ladridos')."
        )
    estado = "🟢 activado" if guard.enabled else "🔴 desactivado"
    return (
        f"Anti-ladridos: {estado}\n"
        f"Al oír un ladrido (umbral {guard.threshold:.0%}) busca al perro con la "
        "cámara; si lo ve, reproduce el audio.\n"
        f"Actúa como máximo cada {guard.settings.bark_alert_cooldown_seconds:.0f}s."
    )


def bark_guard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("🟢 Activar", callback_data="bk:on"),
            InlineKeyboardButton("🔴 Desactivar", callback_data="bk:off"),
        ]]
    )
