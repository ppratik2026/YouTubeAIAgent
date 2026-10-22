FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-noto-core fonts-noto-ui-core tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV DATA_DIR=/app/data PYTHONUNBUFFERED=1
CMD ["python", "-m", "pipeline", "worker"]
