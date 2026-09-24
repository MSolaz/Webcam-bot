"""
Micrófono y altavoz con las utilidades de ALSA (paquete alsa-utils).

- Captura: `arecord` graba de forma continua a 16 kHz, mono, 16 bits. Con
  dispositivos `plughw:...` o `default`, ALSA convierte el formato nativo de
  la tarjeta (44,1/48 kHz, estéreo...) sin que el bot tenga que remuestrear.
- Reproducción: `aplay` con un archivo WAV.

Solo funciona en Linux con acceso a /dev/snd (ver docker-compose.yml).
"""

import logging
import subprocess
import threading

import numpy as np

__all__ = ["AudioError", "Microphone", "SlidingWindow", "play_sound", "SAMPLE_RATE"]

logger = logging.getLogger("webcam-bot")

SAMPLE_RATE = 16000
# Segundos de espera antes de volver a lanzar arecord si se cierra (por
# ejemplo, porque se ha desconectado el micrófono)
_RESTART_DELAY_SECONDS = 30.0


class AudioError(Exception):
    pass


class SlidingWindow:
    """Trocea un flujo continuo de audio en ventanas de `window` muestras,
    solapadas cada `hop` muestras (el mismo troceado que usa YAMNet)."""

    def __init__(self, window: int, hop: int):
        self.window = window
        self.hop = hop
        self._buffer = np.zeros(0, dtype=np.float32)

    def push(self, samples: np.ndarray) -> list:
        """Añade muestras float32 y devuelve las ventanas completas nuevas."""
        self._buffer = np.concatenate([self._buffer, samples])
        windows = []
        while len(self._buffer) >= self.window:
            windows.append(self._buffer[: self.window].copy())
            self._buffer = self._buffer[self.hop:]
        return windows

    def clear(self):
        self._buffer = np.zeros(0, dtype=np.float32)


class Microphone:
    """Graba del micrófono en un hilo propio y llama a `on_window(ventana)`
    (desde ese hilo) con cada ventana float32 en [-1, 1]."""

    def __init__(self, device: str, window: int, hop: int, on_window):
        self.device = device
        self._windows = SlidingWindow(window, hop)
        self._on_window = on_window
        self._chunk_bytes = hop * 2  # 16 bits = 2 bytes por muestra
        self._process = None
        self._thread = None
        self._stopping = threading.Event()

    def start(self):
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="microfono", daemon=True)
        self._thread.start()

    def stop(self):
        self._stopping.set()
        if self._process is not None:
            self._process.terminate()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self):
        while not self._stopping.is_set():
            try:
                self._record()
            except FileNotFoundError:
                logger.error("No se encontró 'arecord': falta el paquete alsa-utils")
                return
            except Exception:
                logger.exception("Error inesperado leyendo el micrófono")
            if not self._stopping.wait(_RESTART_DELAY_SECONDS):
                logger.info("Reintentando abrir el micrófono '%s'", self.device)

    def _record(self):
        self._windows.clear()
        self._process = subprocess.Popen(
            ["arecord", "-q", "-D", self.device, "-t", "raw",
             "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info("Micrófono '%s' abierto", self.device)
        try:
            while True:
                data = self._process.stdout.read(self._chunk_bytes)
                if not data:
                    break
                samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
                for window in self._windows.push(samples):
                    self._on_window(window)
        finally:
            self._process.stdout.close()
            error = self._process.stderr.read().decode(errors="replace").strip()
            self._process.wait()
            if not self._stopping.is_set():
                logger.error(
                    "El micrófono '%s' se ha cerrado (código %s): %s",
                    self.device, self._process.returncode, error or "sin detalles",
                )


def play_sound(path: str, device: str):
    """Reproduce un WAV y espera a que termine. Bloqueante: llamar vía
    asyncio.to_thread. Lanza AudioError si falla."""
    try:
        result = subprocess.run(
            ["aplay", "-q", "-D", device, path],
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise AudioError("No se encontró 'aplay': falta el paquete alsa-utils.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError("La reproducción tardó más de 2 minutos y se canceló.") from exc
    if result.returncode != 0:
        detalle = result.stderr.decode(errors="replace").strip() or "sin detalles"
        raise AudioError(f"No se pudo reproducir '{path}' en '{device}': {detalle}")
