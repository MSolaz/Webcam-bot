import numpy as np

from webcam_bot.detection import DOG_CLASS_ID, _best_dog_confidence

CAT_CLASS_ID = 8


def _detections(*rows):
    """Construye una salida de red con forma 1x1xNx7 a partir de pares
    (class_id, confianza)."""
    data = np.zeros((1, 1, len(rows), 7), dtype=np.float32)
    for i, (class_id, confidence) in enumerate(rows):
        data[0, 0, i, 1] = class_id
        data[0, 0, i, 2] = confidence
    return data


def test_dog_class_id_is_12():
    assert DOG_CLASS_ID == 12


def test_no_detections():
    assert _best_dog_confidence(_detections(), 0.4) == 0.0


def test_returns_best_dog_above_threshold():
    detections = _detections((DOG_CLASS_ID, 0.5), (DOG_CLASS_ID, 0.8))
    assert _best_dog_confidence(detections, 0.4) == np.float32(0.8)


def test_ignores_dogs_below_threshold():
    assert _best_dog_confidence(_detections((DOG_CLASS_ID, 0.3)), 0.4) == 0.0


def test_ignores_other_classes():
    assert _best_dog_confidence(_detections((CAT_CLASS_ID, 0.99)), 0.4) == 0.0
