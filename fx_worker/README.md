# fx_worker

Servicio de render de motion graphics con [HyperFrames](https://github.com/heygen-com/hyperframes) (HTML + GSAP, renderizado con Chrome headless y FFmpeg). Recibe un JSON, compone el vídeo y deja el MP4 en el volumen compartido. Los detalles de por qué este motor y qué se midió están en `spike/RESULTADOS.md`.

Es un servicio **interno** de la red de Docker: no tiene autenticación y solo se publica en `127.0.0.1:8910` para depurar. Atiende **un render a la vez** (el backend ya aplica el carril global; esto es un seguro).

## API

| Método y ruta | Qué hace |
|---|---|
| `GET /health` | `{ok, engine, busy}` |
| `POST /renders` | Valida y lanza un render. `202 {id}`; `400` petición o ruta no válida; `409 busy`; `413` cuerpo de más de 2 MB; `422 video_not_found` |
| `GET /renders/:id` | `{status, progress, message, error, output, seconds}` con `status` = `queued`, `running`, `completed`, `failed` o `cancelled` |
| `DELETE /renders/:id` | Cancela el render en marcha (`202`); `409` si ya terminó |

Los registros terminados se olvidan a la hora.

## Contrato de `POST /renders`

Todas las rutas son **relativas a `MEDIA_DIR`** (sin `/` inicial ni `..`) y los tiempos van en **segundos**, relativos al inicio del clip vertical (t = 0).

```json
{
  "video": "u1/p3/clip_12/vertical.mp4",
  "output": "u1/p3/clip_12/draft.mp4",
  "quality": "draft",
  "fps": 30,
  "duration": 28.4,
  "layout": { "mode": "split", "top_ratio": 0.5 },
  "words": [{ "text": "Urgente", "start": 0.6, "end": 1.0, "speaker": "A" }],
  "speakers": { "A": { "name": "Ana", "role": "periodista", "caption_style": "sans_upper", "is_source": false } },
  "hook": { "text": "Nadie se lo esperaba", "duration": 2 },
  "preset": "editorial"
}
```

Solo `video`, `output` y `duration` son obligatorios. El clip vertical de entrada debe llevar **fotogramas clave densos** (`-g 30`); lo genera `backend/app/pipeline/vertical.py`. El esquema completo está en `src/contract.mjs`.

## Variables de entorno

| Variable | Por defecto | Uso |
|---|---|---|
| `MEDIA_DIR` | `/media` | Volumen compartido con el backend |
| `FX_WORKERS` | `2` | Workers de captura por render: 2 workers = 98 s y 2,6 GB por 38 s de vídeo; 4 apenas mejora y duplica la memoria |
| `PORT` | `3000` | Puerto de escucha |
| `HYPERFRAMES_TELEMETRY` | `0` | Desactiva la telemetría de HyperFrames |

## Pruebas

```bash
npm install
npm test                    # unitarias: contrato, rutas, constructor, linter y servidor (sin Chrome)
npm run test:integration    # render real con Chrome; tarda ~10 s
```
