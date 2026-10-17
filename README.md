# myclippingapp

App web multiusuario para clipear vídeos largos de YouTube y convertirlos en shorts con motion graphics.

Stack: FastAPI + MariaDB, worker con cola en MariaDB, React + Vite, Remotion (fx_worker) y ffmpeg. Docker Compose.

## Arranque

```bash
cp .env.example .env      # rellena claves y contraseñas (ver comentarios dentro)
docker compose up -d --build
```

- Frontend: http://localhost:5074
- API: http://localhost:8800/api/health

El primer usuario que se registra es admin.

## Tests

```bash
docker compose run --rm --no-deps -e DATABASE_URL=sqlite:// backend python -m pytest -q tests
```

Documentación de diseño: `conocimiento_motion_video.md`.
