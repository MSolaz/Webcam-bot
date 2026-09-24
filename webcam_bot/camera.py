"""
Captura de imagen de la webcam con OpenCV.

La cámara se abre y se libera en cada captura (no hay stream persistente).
Todo acceso al dispositivo pasa por Camera.lock para que la captura
manual, la vigilancia periódica y el reset USB no choquen entre sí.
"""

import asyncio

import cv2

__all__ = ["Camera", "CameraError", "encode_jpeg"]


class CameraError(Exception):
    pass


def encode_jpeg(frame) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise CameraError("No se pudo codificar la imagen capturada.")
    return buffer.tobytes()


class Camera:
    def __init__(self, device: str, width: int, height: int):
        self.device = device
        self.width = width
        self.height = height
        # Serializa el acceso al dispositivo: solo un lector a la vez.
        self.lock = asyncio.Lock()

    def _open(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.device)
        if not cap.isOpened():
            raise CameraError(
                f"No se pudo abrir el dispositivo de cámara '{self.device}'. "
                "¿Está conectada y mapeada al contenedor?"
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        return cap

    def read_frame_sync(self, warmup_frames: int):
        """Abre la cámara, descarta fotogramas de calentamiento y devuelve el
        último frame leído (numpy array BGR). Bloqueante: llamar vía
        asyncio.to_thread y con self.lock adquirido."""

        cap = self._open()
        try:
            frame = None
            for _ in range(max(warmup_frames, 1)):
                ok, frame = cap.read()
                if not ok:
                    raise CameraError(
                        "La cámara se abrió pero no devolvió fotogramas "
                        "(¿en uso por otro proceso?)."
                    )
            return frame
        finally:
            cap.release()

    def _capture_jpeg_sync(self, warmup_frames: int) -> bytes:
        return encode_jpeg(self.read_frame_sync(warmup_frames))

    async def capture_jpeg(self, warmup_frames: int) -> bytes:
        async with self.lock:
            return await asyncio.to_thread(self._capture_jpeg_sync, warmup_frames)
