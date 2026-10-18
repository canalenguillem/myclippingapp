#!/usr/bin/env bash
# Matriz de rendimiento: workers x calidad. Una línea JSON por ejecución.
cd "$(dirname "$0")/.."
export HYPERFRAMES_TELEMETRY=0
for q in draft standard; do
  for w in 1 2 4; do
    echo "== quality=$q workers=$w"
    node spike/run.mjs --quality $q --workers $w --out "bench-$q-$w.mp4" 2>&1 | tail -1
  done
done
echo "== FIN"
