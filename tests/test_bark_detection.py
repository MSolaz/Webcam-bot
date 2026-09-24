"""Pruebas con el modelo real: se saltan si no está en models/ (no se
versiona) o si falta ai-edge-litert."""

import os

import numpy as np
import pytest

pytest.importorskip("ai_edge_litert")

from webcam_bot.bark_detection import BarkDetector  # noqa: E402
from webcam_bot.config import Settings  # noqa: E402

settings = Settings.from_env({})
if not os.path.isfile(settings.bark_model):
    pytest.skip("No hay models/ladridos.tflite", allow_module_level=True)


@pytest.fixture(scope="module")
def detector():
    return BarkDetector(settings.bark_model, settings.bark_model_info)


def test_reads_format_and_threshold_from_info(detector):
    assert detector.window_samples == 15600
    assert 0 < detector.threshold < 1


def test_threshold_can_be_overridden():
    detector = BarkDetector(settings.bark_model, settings.bark_model_info, threshold=0.8)
    assert detector.threshold == 0.8


def test_silence_is_not_a_bark(detector):
    assert detector.probability(np.zeros(15600, dtype=np.float32)) < 0.1


def test_rejects_wrong_window_size(detector):
    with pytest.raises(ValueError):
        detector.probability(np.zeros(1000, dtype=np.float32))
