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
  "band": { "y0": 1380, "y1": 1470 },
  "hook": { "text": "Nadie se lo esperaba", "duration": 2 },
  "preset": "editorial",
  "cortinilla": { "at": 8.4, "duration": 3.6, "color": "#DA2E09" }
}
```

Solo `video`, `output` y `duration` son obligatorios. ## Capas de estilo

| Capa | Qué hace |
|---|---|
| Banda de papel | Franja crema rasgada a todo el ancho que **tapa** las filas `band.y0`–`band.y1` (p. ej. subtítulos quemados del origen) con 10 px de margen; sin `band` va centrada en el corte entre el plano corto y la escena completa. Solo en el preset `editorial`. El rasgado es determinista (semilla fija) y siempre sobresale entre 6 y 22 px de la zona protegida |
| Cortinilla de inicio | Opcional. `cortinilla.at` es un segundo del clip **sin** cortinilla (nunca en el último segundo ni dentro de una palabra) y el clip se pausa `duration` s (1–10, por defecto 3,6). El vídeo sale de dos tramos del mismo fichero; bajo los barridos de 0,42 s se ven dos fotogramas congelados (el último del tramo 1 y el primero del tramo 2), así que en pleno color de marca no asoma ni un píxel del clip. Todo lo posterior (subtítulos, B/N) se desplaza con `src/timemap.mjs` (`t_salida = t_origen + duration` si `t_origen >= at`); la duración del MP4 es `duration` del clip + la de la cortinilla |
| Subtítulos | Karaoke por palabra en dos estilos según `speakers[x].caption_style`: `sans_upper` (Inter ExtraBold, MAYÚSCULAS) y `serif_italic` (Cormorant SemiBold cursiva). La palabra activa va en el color de acento; las que aún no se dicen, atenuadas. Frases de ≤ 4 palabras y ~22 letras, con corte tras puntuación, pausas de más de 0,35 s y cambios de speaker |
| Clip citado | Los tramos de los speakers con `is_source: true` salen en blanco y negro (filtro CSS con fundido de 0,2 s); la banda y el texto siguen en color |
| Gancho | Titular de pocas palabras que entra desenfocado; en `editorial` la última palabra va en serif cursiva y color de acento |
| Presets | `editorial` (banda y acento rojo), `hormozi` (sin banda, acento amarillo, trazo negro) y `minimal` (sin banda, texto blanco) |

El clip vertical de entrada debe llevar **fotogramas clave densos** (`-g 30`); lo genera `backend/app/pipeline/vertical.py`. El esquema completo está en `src/contract.mjs`.

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
