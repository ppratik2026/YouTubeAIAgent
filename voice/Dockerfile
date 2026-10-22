# CPU-only voice-clone service (Chatterbox Multilingual). Big image (~3-4 GB) because of PyTorch.
FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# CPU wheels of PyTorch keep the image a lot smaller than the default CUDA ones.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu chatterbox-tts
COPY server.py .

ENV DATA_DIR=/app/data HF_HOME=/app/data/models PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "server.py"]
