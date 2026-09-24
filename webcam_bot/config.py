"""
Configuración del bot, leída de variables de entorno (ver .env.example).

Nada se lee al importar el módulo: la configuración se construye con
Settings.from_env() al arrancar, lo que permite importar el resto de
módulos (y probarlos) sin tener un entorno completo.
"""

import logging
import os
import sys
from dataclasses import dataclass

__all__ = ["Settings", "setup_logging"]

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Carpetas models/ y sounds/ en la raíz del proyecto (junto al paquete webcam_bot/)
_DEFAULT_MODEL_DIR = os.path.join(_PROJECT_DIR, "models")
_DEFAULT_BARK_SOUND_FILE = os.path.join(_PROJECT_DIR, "sounds", "ladrido.wav")
_MODEL_PROTOTXT_NAME = "MobileNetSSD_deploy.prototxt"
_MODEL_WEIGHTS_NAME = "MobileNetSSD_deploy.caffemodel"
_BARK_MODEL_NAME = "ladridos.tflite"
_BARK_MODEL_INFO_NAME = "ladridos_info.json"


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _parse_user_ids(value: str) -> frozenset:
    return frozenset(int(uid.strip()) for uid in value.split(",") if uid.strip())


def _parse_optional_float(value: str):
    value = value.strip()
    return float(value) if value else None


@dataclass(frozen=True)
class Settings:
    bot_token: str
    # Vacío = cualquier usuario puede usar el bot. También son los
    # destinatarios de las alertas de vigilancia.
    allowed_user_ids: frozenset

    camera_device: str = "/dev/video0"
    camera_width: int = 1280
    camera_height: int = 720
    # Nº de fotogramas que se descartan al abrir la cámara para que el sensor
    # ajuste exposición/balance de blancos antes de capturar el definitivo.
    warmup_frames: int = 10

    # --- Vigilancia / detección de perro ---
    model_dir: str = _DEFAULT_MODEL_DIR
    dog_watchdog_enabled: bool = True
    dog_check_interval_seconds: float = 5.0
    dog_alert_cooldown_seconds: float = 60.0
    dog_min_confidence: float = 0.4
    # Menos fotogramas de calentamiento que en la captura manual: esta
    # comprobación se repite cada pocos segundos y no necesita máxima calidad.
    dog_check_warmup_frames: int = 3

    # --- Reset USB de la cámara ---
    # Segundos de margen tras el reset antes de intentar verificarlo con una
    # captura (el driver/kernel tarda un poco en volver a enumerar el
    # dispositivo).
    reset_settle_seconds: float = 5.0

    # --- Anti-ladridos (micrófono + altavoz) ---
    bark_guard_enabled: bool = True
    # Dispositivos ALSA (ver `arecord -L` / `aplay -L` en el servidor)
    audio_input_device: str = "default"
    audio_output_device: str = "default"
    bark_sound_file: str = _DEFAULT_BARK_SOUND_FILE
    # None = usar el umbral_recomendado de ladridos_info.json
    bark_threshold: float | None = None
    bark_alert_cooldown_seconds: float = 60.0
    # Fotos que se hacen (1 por segundo) buscando al perro tras oír un ladrido
    bark_camera_checks: int = 3

    @property
    def model_prototxt(self) -> str:
        return os.path.join(self.model_dir, _MODEL_PROTOTXT_NAME)

    @property
    def model_weights(self) -> str:
        return os.path.join(self.model_dir, _MODEL_WEIGHTS_NAME)

    @property
    def bark_model(self) -> str:
        return os.path.join(self.model_dir, _BARK_MODEL_NAME)

    @property
    def bark_model_info(self) -> str:
        return os.path.join(self.model_dir, _BARK_MODEL_INFO_NAME)

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        """Construye la configuración a partir de un diccionario de
        variables de entorno (por defecto, os.environ)."""
        env = os.environ if env is None else env
        return cls(
            bot_token=env.get("TELEGRAM_BOT_TOKEN", ""),
            allowed_user_ids=_parse_user_ids(env.get("ALLOWED_USER_IDS", "")),
            camera_device=env.get("CAMERA_DEVICE", "/dev/video0"),
            camera_width=int(env.get("CAMERA_WIDTH", "1280")),
            camera_height=int(env.get("CAMERA_HEIGHT", "720")),
            warmup_frames=int(env.get("WARMUP_FRAMES", "10")),
            model_dir=env.get("MODEL_DIR", _DEFAULT_MODEL_DIR),
            dog_watchdog_enabled=_parse_bool(env.get("DOG_WATCHDOG_ENABLED", "true")),
            dog_check_interval_seconds=float(env.get("DOG_CHECK_INTERVAL_SECONDS", "5")),
            dog_alert_cooldown_seconds=float(env.get("DOG_ALERT_COOLDOWN_SECONDS", "60")),
            dog_min_confidence=float(env.get("DOG_MIN_CONFIDENCE", "0.4")),
            dog_check_warmup_frames=int(env.get("DOG_CHECK_WARMUP_FRAMES", "3")),
            reset_settle_seconds=float(env.get("RESET_SETTLE_SECONDS", "5")),
            bark_guard_enabled=_parse_bool(env.get("BARK_GUARD_ENABLED", "true")),
            audio_input_device=env.get("AUDIO_INPUT_DEVICE", "default"),
            audio_output_device=env.get("AUDIO_OUTPUT_DEVICE", "default"),
            bark_sound_file=env.get("BARK_SOUND_FILE", _DEFAULT_BARK_SOUND_FILE),
            bark_threshold=_parse_optional_float(env.get("BARK_THRESHOLD", "")),
            bark_alert_cooldown_seconds=float(env.get("BARK_ALERT_COOLDOWN_SECONDS", "60")),
            bark_camera_checks=int(env.get("BARK_CAMERA_CHECKS", "3")),
        )


def setup_logging():
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
