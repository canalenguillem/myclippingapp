# CLAUDE.md

App web multiusuario para clipear vídeos largos de YouTube y convertirlos en shorts con motion graphics. Estado real en `status.md`; plan en `~/.claude/plans/analiza-el-md-que-playful-parasol.md`; ajustes de estilo F4–F9 en `FASES.md`; conocimiento de motion graphics en `conocimiento_motion_video.md`.

## Reglas de trabajo

1. **Una fase cada vez.** No adelantes trabajo de fases futuras, aunque lo veas fácil o relacionado.
2. **Toda fase acaba con los tests en verde y `status.md` actualizado.** Sin las dos cosas, la fase no está cerrada.
3. **Carril de render global.** Como mucho `RENDER_LANES` jobs `render` en ejecución a la vez en todo el sistema, de cualquier usuario (por defecto 1; el admin lo sube en el `.env` y `fx_worker` lo respeta con `FX_MAX_RENDERS`). Con más de 1, `FX_WORKERS=1` y vigilar la RAM. Cada usuario además tiene su `max_concurrent_jobs` (pantalla «Usuarios» del admin); las subidas a YouTube no cuentan.
4. **Tiempos en segundos como `float`** (nunca milisegundos ni frames fuera del worker de render). **Las rutas guardadas en la BD son relativas a `MEDIA_DIR`**; se resuelven con `app/services/storage.py`, que rechaza rutas que se salgan de `MEDIA_DIR`.
5. **Cuando te corrija estilo o tiempos**, además de arreglar el caso, añade o reescribe la regla en `rules/<area>.md`, con `<area>` entre `subtitulos`, `rotulos`, `cortinillas`, `plan` y `qa`. Si la regla nueva contradice otra, reescribe la antigua en vez de dejar las dos.

## Comandos

```bash
docker compose up -d --build                 # levanta mariadb, backend, worker y frontend
docker compose run --rm --no-deps -e DATABASE_URL=sqlite:// backend python -m pytest -q tests   # tests del backend
```

- `backend` y `worker` comparten la imagen `clippingvideos-app`: reconstruye con `docker compose build backend` y recrea los dos servicios.
- El frontend se sirve con nginx (build de producción): tras tocar `frontend/src/**`, `docker compose up -d --build frontend` (el build ejecuta `tsc`).

## Convenciones

- `.env` tiene secretos reales y no se commitea. Cualquier variable nueva va también a `.env.example`, con el valor vacío.
- Toda tabla de contenido lleva `user_id`, y todo endpoint que reciba un id de recurso usa `get_owned()`: el recurso de otro usuario responde 404.
- Cambios de esquema: migración Alembic nueva en `backend/app/migrations/versions/`, nunca editar una ya aplicada.
- Los jobs son funciones en `app/jobs/handlers.py`; lo que tarde, escribe progreso y log con `ctx.progress()` y `ctx.log()`, y llama a `ctx.check_cancelled()` entre pasos.
