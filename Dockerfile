FROM python:3.12-slim

# Dependencias del sistema necesarias para opencv-python-headless,
# para depurar el dispositivo de vídeo (v4l2-ctl) y para el micrófono y el
# altavoz del anti-ladridos (arecord / aplay)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
        v4l-utils \
        alsa-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY webcam_bot/ ./webcam_bot/
COPY models/ ./models/

CMD ["python", "-m", "webcam_bot"]
