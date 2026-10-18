FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg curl unzip ca-certificates fontconfig fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp descifra firmas de YouTube con un runtime JS; sin deno da HTTP 403.
RUN curl -fsSL https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip \
    && unzip -o /tmp/deno.zip -d /usr/local/bin && chmod +x /usr/local/bin/deno && rm /tmp/deno.zip

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
