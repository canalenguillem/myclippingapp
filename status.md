# Estado del proyecto

Última actualización: 2026-10-18. Plan completo en `~/.claude/plans/analiza-el-md-que-playful-parasol.md`; ajustes de estilo F4–F9 en `FASES.md`; reglas de trabajo en `CLAUDE.md`; conocimiento de motion graphics en `conocimiento_motion_video.md`.

## Objetivo

App web multiusuario para clipear vídeos largos de YouTube: detectar los mejores momentos, convertirlos en shorts verticales con motion graphics (cortinilla de entrada, cortinilla de salida y gráficos ligados a lo que se dice) y subirlos al canal de YouTube que cada usuario configure.

Stack: FastAPI + MariaDB (SQLAlchemy + Alembic), worker con cola en MariaDB, React + Vite, HyperFrames de HeyGen (`fx_worker`) y ffmpeg, todo en Docker Compose.

## Hecho (F0–F6)

| Fase | Contenido | Verificado |
|---|---|---|
| F0 Andamiaje | Compose con `mariadb`, `backend`, `worker`, `frontend`; `.env.example`; Alembic | `/api/health` responde con la BD conectada |
| F1 Auth | Registro, login y logout con argon2; sesión JWT en cookie httpOnly; CSRF por doble envío; el primer usuario es admin; `get_owned()` devuelve 404 si el recurso es de otro usuario | Tests + prueba real por nginx |
| F2 Cola de jobs | Tabla `jobs` como cola; worker con `SKIP LOCKED` y `GET_LOCK`; latido; jobs huérfanos reencolados; límite de jobs por usuario; cancelación; log por fichero y SSE | Tests + prueba real en MariaDB |
| F3 Ingesta | Proyecto desde URL de YouTube (solo `youtube.com` / `youtu.be`); descarga a 1080p con yt-dlp + deno; audio mono 16 kHz; límite de duración por usuario | Tests + importación real |
| **F4 Detección y revisión** | Ver detalle abajo | 160 tests + vídeo real de 14 min + interfaz probada en Chrome |
| **F5 Render vertical** | Carril de render global de 1; clip vertical con ffmpeg (diseño `split`, fotogramas clave densos); `fx_worker` con HyperFrames (HTML + GSAP, banda de papel, subtítulos karaoke en dos estilos, gancho, blanco y negro del clip citado, presets editorial/hormozi/minimal); job `render` con borrador 540x960 y final 1080x1920 (solo aprobado), miniatura, análisis de subtítulos quemados (blanco, verde, amarillo) y fallback a subtítulos ASS si el servicio cae; API (render, cancelar, URLs firmadas, stills); panel de render en el editor | 271 tests + `fx_worker` (43 unitarios y 3 de integración) + clip real de 41,8 s: final 1080x1920 en ~3 min, dos renders seguidos de dos jobs corren uno tras otro, fallback con `fx_worker` parado probado |
| **F6 Cortinillas** | Mapa de tiempos único (backend y `fx_worker`) y posición en un silencio tras frase completa (`cortinilla_at`, automática o elegida en el editor); migración 0004 (sin `outro_enabled`, plantilla `cortinilla` JSON, `cortinilla_default`); `fx_worker` monta el clip en dos tramos con fotogramas congelados bajo los barridos; plantilla `pill_draw` (título con última palabra en serif cursiva, píldora que se dibuja, objeto que orbita, antetítulo) y cortinilla final `cta_subscribe` (siempre, termina en el color de marca); efectos sintetizados (whoosh y brillo); API y página de Plantillas con vista previa sin renderizar (`@hyperframes/player`), plantilla por clip y por proyecto | 303 tests + `fx_worker` (68 unitarios y 6 de integración con Chrome real) + final real del clip 40: 1080x1920, 47,9 s = 41,8 + 3,6 + 2,5, en 157 s; sincronía tras la cortinilla comprobada con la transcripción |

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
| **F7 Gráficos por transcripción** (pasos 1 y parte del 3 hechos: contrato `graphics`, capa y motivos `keyword` (tarjeta abajo) y `emoji` (con escena «salta hasta el objetivo») en `fx_worker`, programador determinista en el backend y render que los manda; orden decidido: motivos tipográficos y línea de tiempo manual → `graphics_planner` → librería de assets → motivos con objeto) | Resto de motivos tipográficos; línea de tiempo editable; `graphics_planner`; librería de assets; motivos con objeto |
| **F8 YouTube por usuario** | Canales con su propio `client_secret.json` cifrado; OAuth con `state` firmado; SEO; subida |
| **F9 QA y pulido** | Checks automáticos; bucle notas → reglas por usuario (`style_rules`, decisión C4); hoja de contactos; limpieza de media |

### Decisiones sin tomar

Detalle completo en la sección «Conflictos pendientes de decisión» del plan.

- Ninguna bloquea F6. Queda por decidir más adelante si entra el presentador-muñeco (F7).

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

- **HyperFrames:** Apache 2.0, sin cuotas por render. Es anterior a 1.0 (0.8.169): fijar la versión y vigilar los cambios incompatibles. El experimento de F5 resolvió los huecos de su documentación (vídeo de origen, subtítulos por palabra, Docker, rendimiento). Remotion queda como plan B (de pago a partir de 4 personas); está en `myMoviPyTests`, carpeta `fx_worker/`, commit `5321d57`.
- **Derechos de autor:** clipear vídeos de terceros requiere permiso del autor o un uso permitido. La app no debe prometer esquivar Content ID.
- **Cuota de YouTube:** ~6 subidas al día por proyecto de Google (cada usuario usa el suyo).
- **CPU y memoria:** con 2 workers y calidad estándar, un vídeo vertical de 38 s tarda ~98 s y usa ~2,6 GB (medido en una máquina de 12 núcleos); el carril global de 1 serializa los renders.
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
- **Estructura del short (C1):** arranca directamente en contenido, con una intro corta del propio clip (~4 s, cortada en un silencio). La cortinilla de inicio es opcional (casilla por clip, valor por defecto en la plantilla de marca, apagada por defecto): entra en el silencio que se elija (por defecto, tras la intro de ~4 s; sin máximo), pausa el clip y dura 3,6 s. La cortinilla final es siempre, sin interruptor; `outro_enabled` se elimina del modelo en F6.
- **Capas de estilo en F5 (C2):** banda de papel, dos estilos de subtítulo, blanco y negro para el clip citado y preset `editorial` van con el porte del render vertical.
- **Vista previa en F6 (C3):** el editor de plantilla de cortinilla tiene vista previa sin renderizar (iframe sobre la composición HTML, a validar en F5).
- **Reglas de estilo por usuario (C4):** tabla `style_rules` en la BD; `rules/` del repo queda como guía de desarrollo.
- **Sin `FX_PARALLEL` (C5):** rige solo el carril global de 1; no hay escalado por réplicas del servicio de render.
- **Motor de animación: HyperFrames de HeyGen (HTML + GSAP)**, en lugar de Remotion; el experimento de F5 salió bien (GO). Remotion queda como plan B.
- **Diseño de pantalla de F5 (O1):** solo `split`: plano corto arriba y escena completa abajo, con la banda y los subtítulos encima aunque la tapen en parte. Más adelante, el hueco de abajo podrá llevar un gameplay o un vídeo del usuario.
- **Alcance de F5 (recortes aprobados el 2026-10-18):** subtítulos en dos estilos, gancho, banda de papel, blanco y negro del clip citado, borrador y final, y stills. El análisis por clip se reduce a detectar subtítulos quemados; cortes de plano y caras (mediapipe) pasan a F7. Zooms de énfasis, emojis, barra de progreso, SFX y música quedan fuera de F5 (los zooms con su whoosh podrían entrar como paso extra opcional).

## Cierre de F5: datos y deuda

- **Medido el 2026-10-18** (clip 40, 41,8 s, 107 palabras, máquina de 12 núcleos): borrador ~72 s; final ~3 min. Dos jobs `render` lanzados a la vez: el segundo esperó en cola a que acabara el primero.
- **Fallback ASS:** con `fx_worker` parado el borrador sale con subtítulos simples (sin banda, estilos ni gancho) y `render_error` empieza por «Aviso:». Arreglado en el cierre: las frases ya no se solapan en el tiempo.
- **Deuda:** subtítulos quemados esporádicos (<25 % del clip) no activan la banda obligatoria; si un render agota sus intentos fuera del handler, el clip se queda en `rendering`; sin probar en el navegador el render final ni el aviso del fallback.

## Cierre de F6: datos y deuda

- **Medido el 2026-10-18** (clip 40, 41,8 s, plantilla «Spain Facts», cortinilla de inicio a los 14,3 s): render final en 157 s. Con cortinilla el vídeo dura clip + 3,6 + 2,5 s.
- **Deuda:** el objeto que orbita es un cuadrado de color hasta que haya subida de logo (librería de assets, F7a); no hay selector de la posición de la cortinilla sobre una forma de onda (solo lista de silencios); un clip con `intro_enabled` sin silencio válido se renderiza sin cortinilla de inicio y solo lo dice `render_error`.
