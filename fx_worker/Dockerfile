# Servicio de render de motion graphics (HyperFrames): Node + Chrome headless + FFmpeg.
FROM node:22-bookworm-slim

# FFmpeg, fuentes (incluye emoji en color) y las librerías que necesita Chrome headless.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg ca-certificates curl procps \
      fonts-liberation fonts-noto-color-emoji \
      libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
      libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

ENV HYPERFRAMES_TELEMETRY=0 NODE_ENV=production
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev --no-audit --no-fund

# Descarga Chrome headless shell en la imagen (no en el primer render).
RUN npx --no-install hyperframes browser ensure || npx --yes hyperframes@0.8.169 browser ensure

COPY . .
EXPOSE 3000
ENV MEDIA_DIR=/media FX_WORKERS=2 PORT=3000
CMD ["node", "src/server.mjs"]
