# Experimento técnico de F5: HyperFrames

Fecha: 2026-10-18. Versión: `@hyperframes/producer` 0.8.169 (anterior a 1.0). Máquina: portátil con 12 núcleos y 15 GB de RAM, Linux, sin GPU (Chrome en modo software). **Resultado: GO.**

Esto es código de prueba, no el servicio final: `build.mjs` genera una composición vertical de 38,1 s con todo lo que se quería comprobar y `run.mjs` la renderiza con la API de Node.

## Qué se probó y qué salió

| Pieza | Resultado |
|---|---|
| Vídeo vertical 1080×1920 a 30 fps, audio estéreo AAC | Correcto |
| Vídeo de origen en dos tramos con `data-media-start`, con la cortinilla en medio (pausa el clip) | Correcto; la duración total es exacta (tramo 1 + cortinilla + tramo 2 + cortinilla final) |
| Fotogramas congelados bajo los barridos de la cortinilla | Funcionan con dos PNG extraídos con ffmpeg; sin ellos se ve negro durante el barrido |
| Subtítulos karaoke por palabra con fuentes locales (`@font-face`) | Correcto |
| `filter: blur()` animado (entrada desenfocada del texto) | Correcto |
| Trazo SVG que dibuja una píldora (`strokeDashoffset`) | Correcto |
| Objeto que orbita por una trayectoria calculada (un `set` por fotograma) | Correcto |
| Barrido curvo con canto blanco (SVG con transformaciones) | Correcto |
| Efectos de sonido y música (`<audio>` con `data-volume` y `data-fade-out`) | Correcto; el audio sale idéntico bit a bit entre renders |
| Progreso desde Node (`createRenderJob` y `executeRenderJob`) | Correcto |
| Cancelación con `AbortSignal` | `RenderCancelledError` al instante, sin fichero a medias y sin procesos huérfanos |
| Determinismo | Dos renders iguales difieren en 23 de 1143 fotogramas, todos en la cola de la cortinilla (desvanecido con desenfoque), con PSNR mínimo de 62 dB: imperceptible |
| Docker sin pantalla | Funciona con `--shm-size=1g`; 89 s frente a 77–84 s en el equipo |
| Equipo frente a Docker | PSNR medio de 41 dB, mismo aspecto a la vista; en producción se usa solo Docker |
| Vista previa con `@hyperframes/player` | Funciona en el navegador sin renderizar: carga la composición, salta con `seek`, reproduce vídeo con subtítulos y da la duración correcta |

## Rendimiento (38,1 s de vídeo, 1143 fotogramas)

| Calidad | 1 worker | 2 workers | 4 workers |
|---|---|---|---|
| `draft` | 105 s · 1,7 GB | 73 s · 2,6 GB | 62 s · 5,2 GB |
| `standard` | 141 s · 2,1 GB | 98 s · 2,6 GB | 95 s · 5,2 GB |

Con 2 workers se consigue casi lo mismo que con 4 usando la mitad de memoria. Recomendación para el servicio: **2 workers** por defecto (configurable), calidad `draft` para revisar y `standard` para el final. Un short de ~30 s con cortinillas ronda 1,5–2 minutos de render.

## Reglas aprendidas para el servicio

1. **Los clips de origen deben llevar fotogramas clave densos** (`-g 30 -keyint_min 30 -movflags +faststart`). Con un fotograma clave cada 8 s, HyperFrames avisa de «fallos al buscar y congelaciones». Afecta al `make_vertical_clip` que se porta en F5.
2. **Todo `<audio>` necesita `id`**; sin él sale **mudo** en el render. Los `<video>` con sonido necesitan `data-has-audio="true"`. `hyperframes lint` lo detecta.
3. **La línea de tiempo GSAP debe llegar hasta la duración de la composición**; si no, la vista previa dura menos que el vídeo. Se añade `tl.set({}, {}, total)`.
4. **GSAP en local**, sin CDN, y las fuentes como ficheros del proyecto de render.
5. **Solo lógica determinista**: sin `Date.now()` ni `Math.random()`.
6. El **orden de capas** manda: el panel del barrido va debajo del texto, no encima.
7. Desactivar la telemetría: `HYPERFRAMES_TELEMETRY=0`.
8. En Docker hacen falta FFmpeg, fuentes (con emoji en color), las bibliotecas de Chrome y `hyperframes browser ensure` para bajar Chrome headless shell en la imagen. Ver `../Dockerfile`.
9. El servidor de la vista previa debe admitir `Range` y el componente necesita una relación de aspecto en el CSS (`aspect-ratio: 1080 / 1920`).
10. Variables de entorno del render que interesan al servicio: `PRODUCER_MAX_WORKERS`, `PRODUCER_LOW_MEMORY_MODE`, `HYPERFRAMES_BROWSER_PATH`, `PRODUCER_RENDERS_DIR`.

## Hallazgos posteriores (paso 5 de F5)

- **Los tratamientos de color de HyperFrames (`data-color-grading`) usan WebGL y son inviables sin GPU.** Con Chrome en modo software, un clip de 4 s tardaba más de 150 s (solo arrancar los navegadores ya llevaba ~36 s) frente a ~7 s sin el tratamiento. El blanco y negro del clip citado se hace con un filtro CSS `grayscale()` animado con GSAP sobre un contenedor del vídeo (+0,6 s).
- **La banda de papel con `drop-shadow` cuesta unas décimas** (6,6 s sin banda, 6,9 s con ella en un clip de 4 s); se mantiene.
- **Un servicio de larga vida necesita un proceso `init`** (`init: true` en el compose): sin él, los procesos de Chrome que terminan quedan como zombis colgando del `node` del contenedor.
- **Las pruebas que lanzan Chrome pueden dejar navegadores huérfanos** si el proceso de test muere (un test con tiempo agotado dejó 8 navegadores al 900 % de CPU y falseó las mediciones). Medir siempre con la máquina en reposo (`uptime`) y limpiar con `pkill -f chrome-headless-shell`.

## Sin probar todavía

- El resto de motivos de F7 y los tratamientos de audio (ducking con `data-automation`).
- `PRODUCER_LOW_MEMORY_MODE` y el renderizado con GPU.
- Varios renders seguidos en un mismo proceso (el servicio real renderiza de uno en uno por el carril global).

## Cómo repetirlo

```bash
cd fx_worker
npm install
./spike/make-assets.sh                 # clip de origen y sonidos de prueba (se ignoran en git)
HYPERFRAMES_TELEMETRY=0 node spike/run.mjs --quality draft --workers 2
./spike/bench.sh                       # matriz de rendimiento
```
