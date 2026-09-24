"""
Detección de ladridos con el modelo entrenado en Colab
(notebooks/entrenar_ladridos.ipynb).

El .tflite incluye YAMNet + el clasificador: recibe una ventana de audio
tal cual y devuelve la probabilidad de ladrido. El formato de entrada, los
nombres de entrada/salida y el umbral recomendado se leen de
ladridos_info.json, que se genera junto al modelo.

Se ejecuta con ai-edge-litert (LiteRT), sin necesidad de TensorFlow.
"""

import json
import threading

import numpy as np

__all__ = ["BarkDetector"]


class BarkDetector:
    def __init__(self, model_path: str, info_path: str, threshold: float | None = None):
        # Importación diferida: solo hace falta si hay modelo de ladridos
        from ai_edge_litert.interpreter import Interpreter

        with open(info_path, encoding="utf-8") as f:
            info = json.load(f)
        entrada = info["entrada"]
        if entrada["sample_rate"] != 16000:
            raise ValueError(
                f"El modelo espera audio a {entrada['sample_rate']} Hz; el bot "
                "solo graba a 16000 Hz."
            )
        self.window_samples = int(entrada["muestras"])
        self._input_name = entrada["nombre"]
        self._output_name = info["salida"]["nombre"]
        self.threshold = (
            float(threshold) if threshold is not None else float(info["umbral_recomendado"])
        )
        self._runner = Interpreter(model_path=model_path).get_signature_runner()
        # El intérprete de LiteRT no se puede usar desde dos hilos a la vez
        self._lock = threading.Lock()

    def probability(self, window: np.ndarray) -> float:
        """Probabilidad (0-1) de que la ventana contenga un ladrido. `window`
        son `window_samples` muestras float32 mono en [-1, 1]."""
        audio = np.asarray(window, dtype=np.float32)
        if audio.shape != (self.window_samples,):
            raise ValueError(
                f"Se esperaban {self.window_samples} muestras y llegaron {audio.shape}"
            )
        with self._lock:
            result = self._runner(**{self._input_name: audio})
        return float(np.asarray(result[self._output_name]).ravel()[0])
