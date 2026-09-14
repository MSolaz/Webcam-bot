"""
Detección de perro con MobileNet-SSD (OpenCV DNN).

Modelo ligero, pensado para correr en CPU: red MobileNet-SSD (Caffe)
entrenada sobre el dataset Pascal VOC (20 clases + fondo). No añade
dependencias nuevas: el módulo `cv2.dnn` ya viene incluido en
opencv-python-headless.

Los pesos del modelo NO se incluyen en este repositorio por su tamaño
(~23 MB) — se descargan una vez siguiendo las instrucciones del README,
sección "Detección automática de perro".
"""

# Orden de clases con el que se entrenó este MobileNet-SSD concreto
# (Pascal VOC). El índice importa: tiene que coincidir con la salida
# de la red.
VOC_CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus",
    "car", "cat", "chair", "cow", "diningtable", "dog", "horse",
    "motorbike", "person", "pottedplant", "sheep", "sofa", "train",
    "tvmonitor",
]
DOG_CLASS_ID = VOC_CLASSES.index("dog")

# Tamaño de entrada que espera esta red
INPUT_SIZE = (300, 300)


def load_net(prototxt_path: str, weights_path: str):
    """Carga la red desde los archivos .prototxt y .caffemodel."""
    import cv2

    return cv2.dnn.readNetFromCaffe(prototxt_path, weights_path)


def _best_dog_confidence(detections, min_confidence: float) -> float:
    """Recorre la salida cruda de la red (forma 1x1xNx7) y devuelve la
    confianza más alta entre las detecciones de clase 'dog' que superan
    el umbral. 0.0 si no hay ninguna.

    Separado de find_dog() para poder probarlo con datos sintéticos sin
    necesidad de cargar la red real.
    """
    best = 0.0
    for i in range(detections.shape[2]):
        class_id = int(detections[0, 0, i, 1])
        confidence = float(detections[0, 0, i, 2])
        if class_id == DOG_CLASS_ID and confidence >= min_confidence:
            best = max(best, confidence)
    return best


def find_dog(net, frame, min_confidence: float = 0.4):
    """Ejecuta la detección sobre un frame BGR (numpy array de OpenCV).

    Devuelve (encontrado: bool, confianza_maxima: float).
    """
    import cv2

    blob = cv2.dnn.blobFromImage(
        cv2.resize(frame, INPUT_SIZE), 0.007843, INPUT_SIZE, 127.5
    )
    net.setInput(blob)
    detections = net.forward()

    best = _best_dog_confidence(detections, min_confidence)
    return best >= min_confidence, best
