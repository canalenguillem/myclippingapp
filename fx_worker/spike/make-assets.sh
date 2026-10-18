#!/usr/bin/env bash
# Prepara los medios del experimento (se ignoran en git): clip de origen vertical, sonidos y música sintéticos.
set -euo pipefail
cd "$(dirname "$0")/assets"
SRC="${1:-../../../videos_ejemplo/WhatsApp Video 2026-10-17 at 14.38.17.mp4}"

# Clip de origen: 32 s verticales 1080x1920 a 30 fps con audio.
ffmpeg -v error -y -ss 10 -t 32 -i "$SRC" -vf "scale=1080:1920,fps=30" -c:v libx264 -crf 18 -pix_fmt yuv420p -g 30 -keyint_min 30 -movflags +faststart -c:a aac -b:a 160k -ar 48000 source.mp4
# Whoosh: ruido rosa filtrado con fundidos.
ffmpeg -v error -y -f lavfi -i "anoisesrc=d=0.7:c=pink:a=0.6:r=48000" -af "highpass=f=300,lowpass=f=3000,afade=t=in:d=0.25,afade=t=out:st=0.3:d=0.4,volume=0.8" whoosh.wav
# Pop corto.
ffmpeg -v error -y -f lavfi -i "sine=f=520:d=0.12:r=48000" -af "afade=t=out:st=0.03:d=0.09,volume=0.7" pop.wav
# Cama musical: acorde grave con trémolo, 40 s.
ffmpeg -v error -y -f lavfi -i "sine=f=110:d=40:r=48000" -f lavfi -i "sine=f=165:d=40:r=48000" -filter_complex "[0][1]amix=inputs=2,tremolo=f=0.5:d=0.4,volume=0.6" music.wav
ls -la
