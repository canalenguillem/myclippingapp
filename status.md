# Estado del proyecto

Última actualización: 2026-10-17. Plan completo en `~/.claude/plans/analiza-el-md-que-playful-parasol.md`; ajustes de estilo F4–F9 en `FASES.md`; reglas de trabajo en `CLAUDE.md`; conocimiento de motion graphics en `conocimiento_motion_video.md`.

## Objetivo

App web multiusuario para clipear vídeos largos de YouTube: detectar los mejores momentos, convertirlos en shorts verticales con motion graphics (cortinilla de entrada, cortinilla de salida y gráficos ligados a lo que se dice) y subirlos al canal de YouTube que cada usuario configure.

Stack: FastAPI + MariaDB (SQLAlchemy + Alembic), worker con cola en MariaDB, React + Vite, Remotion (`fx_worker`) y ffmpeg, todo en Docker Compose.

## Hecho (F0–F4)

| Fase | Contenido | Verificado |
|---|---|---|
| F0 Andamiaje | Compose con `mariadb`, `backend`, `worker`, `frontend`; `.env.example`; Alembic | `/api/health` responde con la BD conectada |
| F1 Auth | Registro, login y logout con argon2; sesión JWT en cookie httpOnly; CSRF por doble envío; el primer usuario es admin; `get_owned()` devuelve 404 si el recurso es de otro usuario | Tests + prueba real por nginx |
| F2 Cola de jobs | Tabla `jobs` como cola; worker con `SKIP LOCKED` y `GET_LOCK`; latido; jobs huérfanos reencolados; límite de jobs por usuario; cancelación; log por fichero y SSE | Tests + prueba real en MariaDB |
| F3 Ingesta | Proyecto desde URL de YouTube (solo `youtube.com` / `youtu.be`); descarga a 1080p con yt-dlp + deno; audio mono 16 kHz; límite de duración por usuario | Tests + importación real |
| **F4 Detección y revisión** | Ver detalle abajo | 160 tests + vídeo real de 14 min + interfaz probada en Chrome |

### Detalle de F4

- **Estado del proyecto** como Enum de Python (`downloading` → `transcribing` → `detecting` → `ready` \| `failed`), guardado como texto con validación; migración `0002`.
- **Diarización**: AssemblyAI con `speaker_labels`; `words.json` v2 con `speaker` por palabra, `segments` por utterance y `revision`. Los proyectos sin `speaker` lo indican en la interfaz y ofrecen re-transcribir (no pisa correcciones manuales sin `force`).
- **Silencios**: RMS en ventanas de 50 ms, umbral −45 dB, mínimo 0,10 s → `silences.json`.
- **Detector de clips** (`clip_detector`): construye frases desde las palabras (no usa `segments`: en un monólogo es una sola utterance), pide `hook`, `emphasis_words` y `parts`, y valida la respuesta del modelo. Los límites del clip se ajustan con esta prioridad: final de frase con silencio > final de frase > pausa interna con silencio. Los énfasis se guardan como `{start, text}` en segundos absolutos y aceptan frases del modelo.
- **Job `detect`** encadenado tras `ingest`; re-detectar sustituye solo los clips sin trabajar y conserva los aprobados.
- **API de clips**: listar, ver, editar (campos acotados; el resto da 422), aprobar, desaprobar, borrar, re-detectar. Edición de transcripción (texto sin tocar tiempos; speakers por rango) con control de revisión y bloqueo de fichero.
- **Vídeo en el navegador**: URLs firmadas con caducidad (`/api/media/...`) con soporte de `Range`.
- **Interfaz**: detalle de proyecto (clips con score, fichas de speakers, transcripción editable) y editor de clip (vídeo, recorte, layout, aprobar).

### Resultado con datos reales (vídeo de 14,2 min, un solo orador)

Tras el ajuste de límites: 15 de 16 cortes caen en silencio y 7 de 8 clips acaban en final de frase (el restante acaba en una coma, tras una pausa). Antes del ajuste, 4 de 8 cortes caían en silencio.

### Cómo se usa ahora

1. `docker compose up -d --build` y abrir `http://localhost:5074`.
2. Registrarse (el primero queda como admin).
3. En Proyectos, pegar un enlace de YouTube. El job descarga, transcribe y detecta clips; el progreso se ve en Jobs.
4. En el proyecto: poner nombre y cargo a los speakers, corregir la transcripción, revisar los clips y aprobarlos. En el editor de clip se ajusta el inicio y el fin viendo el vídeo.

## Pendiente

| Fase | Contenido |
|---|---|
| **F5 Render vertical** | Portar `make_vertical_clip`, `render_clip`, `fx_client` y `fx_worker`; carril de render global de 1; análisis por clip; draft 540x960 y final tras aprobar; stills (ajustes de FASES.md; ver conflictos) |
| **F6 Cortinillas** | Intro corta del clip; cortinilla de inicio opcional (pausa el clip); cortinilla final siempre; plantillas de marca por usuario |
| **F7 Gráficos por transcripción** | Librería de assets; motivos con objeto; `graphics_planner` |
| **F8 YouTube por usuario** | Canales con su propio `client_secret.json` cifrado; OAuth con `state` firmado; SEO; subida |
| **F9 QA y pulido** | Checks automáticos; bucle notas → reglas; hoja de contactos; limpieza de media |

### Decisiones sin tomar (C2–C5 bloquean F5/F6, no F4)

Detalle completo en la sección «Conflictos pendientes de decisión» del plan.

- **C2** Si `PaperBand`, los dos estilos de subtítulo, `Grayscale` y el preset `editorial` van en F5 (FASES) o F6 (plan).
- **C3** Si `@remotion/player` va en F6 (FASES) o F9 (plan).
- **C4** Si `rules/` es global o por usuario (F9).
- **C5** Si se elimina `FX_PARALLEL` y se reescribe el aviso de escalado tras fijar el carril global de 1.
- **O1** `v1725` usa pantalla completa + banda inferior, que no es el layout `split`.

## Deuda técnica y problemas conocidos

- **Proyecto atascado:** si un job muere fuera de su handler, el proyecto se queda en el estado en curso. Hay que marcarlo como fallido desde el worker. (F9)
- **Ficheros con dueño root:** los contenedores escriben en `media/` como root y el usuario del host no puede borrarlos. Correr los contenedores con el UID del host. (F9)
- **Sin límite de intentos de login.** (F9)
- **Interfaz sin tests automáticos.** El typecheck corre en el build; el flujo se probó a mano en Chrome (proyecto, speakers, corrección de palabra, asignación de rango, re-detectar, editor de clip con vídeo, guardar y aprobar). Sin probar en navegador: el botón de re-transcribir y el borrado de clips.
- **Transcripciones muy largas:** la vista renderiza todas las palabras sin virtualizar; con vídeos de horas irá lenta. (F9)
- **Énfasis de clips ya aprobados:** re-detectar no los recalcula; un clip aprobado antes de mejorar el mapeo puede seguir sin palabras de énfasis.
- **Silencios de proyectos antiguos:** se midieron con mínimo de 0,15 s; solo se recalculan al re-transcribir un proyecto sin `silences_path`. No hay datos reales afectados todavía.
- **Final de clip en coma:** un clip puede acabar en una coma tras una pausa cuando no hay un final de frase al alcance (8 s).
- **El editor de clip no muestra los silencios** ni la forma de onda; el recorte es por números y por palabras.
- **Logout sin CSRF:** a propósito, riesgo bajo.
- **El vídeo `jNQXAC9IJRE` sale como no disponible** en yt-dlp; es cosa de ese vídeo, no del código.

## Riesgos y avisos

- **Licencia de Remotion:** gratis para particulares y empresas pequeñas; una app multiusuario comercial con más gente necesita licencia de empresa.
- **Derechos de autor:** clipear vídeos de terceros requiere permiso del autor o un uso permitido. La app no debe prometer esquivar Content ID.
- **Cuota de YouTube:** ~6 subidas al día por proyecto de Google (cada usuario usa el suyo).
- **CPU:** Remotion tarda ~1–3 min por clip de 30 s con `FX_CONCURRENCY=1`; el carril global de 1 serializa los renders.
- **Costes de API:** AssemblyAI (con diarización) por minuto de audio y OpenAI por detección y SEO; se pagan con las claves del `.env`. El modelo de detección se cambia con `OPENAI_CLIP_MODEL` (por defecto `gpt-4o`).
- **La calidad de los clips depende del modelo:** algunos empiezan sin el contexto necesario («esta institución…»). La revisión humana en el editor es parte del flujo.

## Decisiones tomadas

- Proyecto nuevo copiando solo la parte de clipping del repo `myMoviPyTests`; no se portan plantas, reels, ComfyUI ni campañas Whop.
- MariaDB en lugar de SQLite, con migraciones Alembic.
- Email + contraseña con JWT en cookie.
- Cada usuario aporta su propio `client_secret.json` de Google Cloud.
- Cola de jobs en MariaDB, sin Redis.
- Los handlers de jobs son funciones Python, no subprocesos de scripts.
- Se transcribe una sola vez el vídeo entero y los clips se cortan de esa transcripción.
- Los énfasis se guardan por tiempo absoluto y texto, no por índice de palabra.
- El estado del proyecto es un Enum de Python guardado como texto, no un `ENUM` nativo de MariaDB.
- Los cortes de clip priorizan acabar en una frase completa antes que en un silencio.
- **Estructura del short (C1):** arranca directamente en contenido, con una intro corta del propio clip (~4 s, cortada en un silencio). La cortinilla de inicio es opcional (casilla por clip, valor por defecto en la plantilla de marca, apagada por defecto): entra tras la intro, pausa el clip y dura 3,6 s. La cortinilla final es siempre, sin interruptor; `outro_enabled` se elimina del modelo en F6.
