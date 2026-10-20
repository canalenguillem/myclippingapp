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
| **F7 Gráficos por transcripción** (pasos 1, 4, F7a y la parte básica de F7b hechos: **librería de imágenes** (subida, normalización a PNG recortado al contenido, sin EXIF, máx. 5 MB y 200 por usuario) y motivo `image` con estilos (tal cual, tarjeta de papel, silueta, rojo de marca) y efectos (entra y sale, se vaporiza, se parte); emoji también se vaporiza; **panel «Gráficos» en el editor**: línea de tiempo (gancho, cortinilla, ventanas reales y descartados), lista editable, añadir en la palabra elegida o en el instante actual, emojis predefinidos y plan del programador en vivo (`POST /api/clips/{id}/graphics-plan`); contrato `graphics`, capa y motivos `keyword` (tarjeta abajo) y `emoji` (con escena «salta hasta el objetivo») en `fx_worker`, programador determinista en el backend y render que los manda; orden decidido: motivos tipográficos y línea de tiempo manual → `graphics_planner` → librería de assets → motivos con objeto) | Resto de motivos tipográficos; línea de tiempo editable; `graphics_planner`; librería de assets; motivos con objeto |
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

## Diseños de pantalla (actualizado el 2026-10-18)

- **`split`**: plano corto arriba y escena completa abajo. **`full`** (nuevo, a petición del usuario para vídeos de un orador a pantalla): el vídeo nítido ocupa `top_ratio` del alto (por defecto 65 % al cambiar desde el editor) con encuadre y zoom del clip, y debajo va una copia del mismo vídeo muy difuminada y oscurecida donde caben los gráficos; la banda de papel y los subtítulos van en el corte. `facecam` sigue sin renderizarse. Amplía la decisión O1.
- En `full` los gráficos comparten el hueco difuminado (arriba de la zona de Shorts, y < 1632 px): nunca hay dos a la vez (el programador usa `single_lane`). Si un clip lleva una tarjeta y una escena de emoji a la vez, gana la más prioritaria.

## Imágenes en los gráficos (F7a/F7b, 2026-10-18)

- `POST /api/assets` (multipart: `file`, `name`), `GET/PATCH/DELETE /api/assets`. Las imágenes viven en `media/u{id}/assets/{id}.png`; borrar una que usa algún clip da 409. Solo se usan las que sube el usuario: el render descarta con motivo un gráfico cuya imagen ya no existe o es ajena.
- Un gráfico de imagen se guarda como `{type: "image", at, asset_id, style, effect}`; el job lo traduce a la ruta del PNG para `fx_worker`. La imagen cuenta como gráfico grande (prioridad 6, mayor que la tarjeta).
- **Deuda:** sin recorte automático de fondo (rembg): un PNG con fondo se vaporiza con su fondo; el logo que orbita en la cortinilla aún se asigna a mano (`logo_path`), y las imágenes no se pueden compartir entre usuarios.

## Entradas, explosión y texto libre (F7, 2026-10-18)

- **Entradas** de los gráficos de imagen: aparece con rebote, entra de un golpe (llega acelerando, golpea EN la palabra, rebota y tiembla el plano), cae desde arriba (rebota al llegar), desde la izquierda, derecha o arriba. **Efectos** en la palabra: se queda, se vaporiza, se parte o **explota** (fragmentos radiales con gravedad y anillo de onda; también para emojis sueltos). Sonidos sintetizados: whoosh, golpe sordo, polvo y crujido; golpear y explotar en la misma palabra suena un solo golpe.
- **Texto libre:** `POST /api/graphics/interpret` traduce una frase («el guante da un golpe y explota») a entrada, efecto y estilo. Primero palabras clave en español (sin red); si no reconoce nada y hay clave de OpenAI, pregunta al modelo con un JSON cerrado y valida la respuesta. No genera código: solo elige entre las piezas conocidas, y el editor enseña lo entendido para corregirlo.
- **Deuda:** el golpe da contra la pantalla (no sobre otro objeto de la escena); el temblor sacude solo el vídeo (no los gráficos); no hay selector de dirección del golpe (siempre desde la izquierda).

## Próximo paso decidido (2026-10-18)

- **Mañana: F8, subida automática a YouTube** (canal @SpainFactsjjj), antes del `graphics_planner`. Motivo: el usuario ya da por buenos los shorts que salen y quiere publicarlos sin pasos manuales. Mientras tanto, el panel de render tiene un botón «Descargar» (sin commitear aún) para subir a mano desde YouTube Studio.
- Después de F8: `graphics_planner`, motivos `counter` / `strike` / `lower_third`, y los subtítulos quemados del original.

## F8 en curso (2026-10-19)

- Hecho: canales de YouTube por usuario (`/api/channels`) con `client_secret.json` **subible y reemplazable desde la web** (validado: solo servidores de Google; cifrado con Fernet; nunca se devuelve; sustituirlo desconecta el canal), OAuth con `state` firmado (HMAC, caduca a 10 min), callback `/api/youtube/callback`, lectura del nombre y avatar del canal, página **Canales** (URI de redirección a registrar, subir o cambiar JSON, conectar, reconectar con otra cuenta y desconectar). 382 tests.
- Falta: job `upload` (con `publishAt` y privacidad por defecto privada), SEO (título, descripción y etiquetas), botón «Subir» en el clip y subida real del short del clip 40.
- Aviso: `client_secret*.json` está en `.gitignore`; el usuario lo tenía en la raíz del repo y se sube desde la web.

## F8: subida a YouTube hecha, pendiente de la primera subida real (2026-10-19)

- Hecho: textos SEO con el modelo (título, descripción con `#Shorts` y etiquetas, según idioma y reglas del canal; plan B sin modelo; siempre revisables), guardado de textos, job `upload` con subida reanudable (renueva el acceso con el refresh_token, errores de la API traducidos, no duplica en reintentos, cancelable), API (`/seo/generate`, `/seo`, `/upload`) y panel «Subir a YouTube» en el editor con el canal de destino bien visible y confirmación antes de subir. Migración 0006. 404 tests.
- **Pendiente:** primera subida real. El canal conectado hoy es «Salud Senior +60», NO @SpainFactsjjj: hay que reconectar eligiendo la cuenta correcta en Canales. No se ha subido nada a YouTube.

## graphics_planner (F7, 2026-10-19)

- `POST /api/clips/{id}/graphics-plan/suggest` propone gráficos desde la transcripción del recorte y la librería de imágenes: el modelo elige la palabra gancho (por índice; el tiempo sale de la palabra, no del modelo), el motivo (emoji con objetivo y efecto, tarjeta de texto, imagen con estilo, entrada y efecto) y una razón corta; `graphics_schedule` impone después las reglas y lo que el usuario ya tiene en el formulario manda (lo propuesto solo entra si cabe). Plan B sin modelo: diccionario palabra → emoji (cosas, cifras e instituciones). Máx. un gráfico cada ~6 s. No guarda nada.
- Política de contenido: sin emojis de colectivos (tonos de piel, banderas salvo 🇪🇸); el prompt lo prohíbe y el código lo filtra.
- Editor: botón «✨ Sugerir gráficos con IA» en el panel «Gráficos»; añade lo propuesto a la lista con su razón y se revisa, cambia o quita antes de guardar. Probado con el clip 31: 9 propuestas razonables. 420 tests.
- **Deuda:** no tiene en cuenta el plano (caras) ni el contenido visual; las propuestas con imágenes de la librería dependen de que el nombre del asset encaje con la palabra.

## Despliegue en la Debian de la LAN (2026-10-19)

- Instalada en `192.168.1.75`, carpeta `~/code/clippingWill` (clon de GitHub por SSH), frontend en el puerto **8093** (`http://192.168.1.75:8093`). La API (18800) y el servicio de render (18910) solo escuchan en `127.0.0.1`. Instalación nueva y vacía (sin datos ni vídeos del equipo de desarrollo); `ALLOW_REGISTRATION=true` hasta que el usuario cree su cuenta, `FX_WORKERS=1` por la memoria (11 GB con otros servicios).
- Conviven con otra copia antigua de la app (`intro_python_*`, puertos 5074/8800/8910): por eso los puertos de depuración son configurables en `.env`.
- Actualizar: `cd ~/code/clippingWill && git pull --ff-only && docker compose up -d --build`. Copia de la BD: `docker compose exec -T mariadb sh -c 'mariadb-dump -uroot -p"$MARIADB_ROOT_PASSWORD" --single-transaction clipping' > backup.sql`.
- Pendiente del usuario: publicar `clipp.enguillem.es` con su proxy hacia `192.168.1.75:8093`, cambiar `PUBLIC_BASE_URL` a https, y registrar el URI de OAuth de Google. Pendiente mío: límite de intentos de login antes de exponerla.

## Migración a la Debian hecha (2026-10-19)

- Copiados a `192.168.1.75:~/code/clippingWill`: la base de datos entera (1 usuario, 1 proyecto, 10 clips, 3 imágenes, 1 canal, 1 plantilla), la carpeta `media/` (60 ficheros, 689 MB; sin `media/ref`) y las **mismas `APP_ENCRYPTION_KEY` y `JWT_SECRET`** del equipo de desarrollo, por lo que el `client_secret` y el token de YouTube se descifran y el canal sigue conectado. `PUBLIC_BASE_URL=https://clipp.enguillem.es` y `ALLOW_REGISTRATION=false`. Copia del volcado en `~/code/clippingWill/backups/` (permisos 600).
- Las dos instancias (desarrollo y Debian) comparten el mismo canal y token de YouTube: no pasa nada por renovar el acceso desde las dos, pero conviene trabajar en una sola para no duplicar subidas.
- La carpeta `media/` de la Debian es del usuario `guillem` (la dejó creada Docker como root; se reasignó con un contenedor).

## Límite de intentos de login (2026-10-19)

- Ventana deslizante de 15 min guardada en la BD (`login_failures`, migración 0007): **5 fallos por email** y **20 por IP** bloquean con 429 y `Retry-After`; durante el bloqueo ni se comprueba la contraseña; el bloqueo caduca solo; un login correcto borra los fallos de ese email; un email inexistente se cuenta igual (no se revela si existe). Ajustable con `LOGIN_WINDOW_SECONDS`, `LOGIN_MAX_PER_EMAIL`, `LOGIN_MAX_PER_IP`.
- IP real: solo se confía en `X-Forwarded-For` si el vecino TCP es de una red de confianza (privada, loopback, CGNAT); se recorre de derecha a izquierda y manda la primera dirección no privada, así que una IP falseada a la izquierda no sirve. Llegando directo desde fuera, la cabecera se ignora.
- F8 verificada con Google real por el usuario (subida automática a su canal funciona). 439 tests.

## Subir el borrador (2026-10-19)

- `POST /api/clips/{id}/upload` admite `source: "final" | "draft"` (por defecto `final`). Con `draft` sube el borrador vigente (540×960, más comprimido) sin esperar al render final; el panel «Subir a YouTube» ofrece los dos, elige el final si existe, y avisa de la menor calidad del borrador. El job guarda en el log cuál se subió.

## Objeto que orbita elegible y canal por defecto del proyecto (2026-10-19)

- **Plantillas:** la cortinilla tiene un selector «Objeto que orbita» con las imágenes de la librería (`cortinilla.orbit_asset_id`); la vista previa muestra la imagen elegida (data URI de 160 px) y el render la usa (gana a `logo_path`, que queda de respaldo). Borrar una imagen usada por una plantilla da 409.
- **Proyecto:** selector «Canal de YouTube al que irán los vídeos» (`PATCH /api/projects/{id}` con `default_channel_id`): lo toman los clips nuevos y los existentes aún sin canal (nunca se pisa el de un clip que ya lo tiene ni los subidos). 451 tests.

## Hablantes conocidos y reproductor karaoke (2026-10-19)

- `GET /api/speakers/known?exclude_project=` devuelve los hablantes con nombre que el usuario ya ha puesto en sus proyectos (cargo y estilo más recientes, nº de vídeos). El panel de speakers ofrece «Elegir de mis otros vídeos…» (rellena nombre, cargo, estilo y «clip citado») y autocompleta el nombre al escribirlo.
- La transcripción tiene al lado el vídeo fuente: mientras suena se ilumina la palabra, el panel dice «Habla ahora: X» y marca su tarjeta con 🔊; los controles son −5/+5 s, velocidad y «Seguir el texto» (la caja se desplaza sola). Cada turno tiene un ▶ con su hora para saltar ahí, y en una selección hay «▶ Escuchar» (reproduce solo ese rango antes de asignarlo a un speaker).
- **Lección:** un `<video>` dentro de un contenedor `position: sticky` junto a una columna muy alta (la transcripción de ~4.800 palabras) colgaba la pestaña. No usar `sticky` con vídeos en páginas largas; el reproductor va al lado de la caja de transcripción, que ya tiene su altura.
- Corrección de la banda de papel en los ojos (clip 33): la detección de subtítulos quemados ya no busca en el 45 % de arriba y exige ≥ 40 % de persistencia.

## Encuadre que sigue al hablante

- Nuevo valor `focus="speaker"` (sin migración; `Clip.focus` es texto). Cada speaker tiene `focus_x` (0 izquierda … 1 derecha) en `Project.speakers`.
- `app/pipeline/focus.py`: `build_track` agrupa las palabras por speaker (las interjecciones < 1 s no mueven el plano; en silencios se mantiene la posición) y `x_expr` genera la expresión de `crop` de ffmpeg con transiciones suaves de 0,25 s. Funciona en `split` y `full`.
- El job de render calcula las palabras del clip antes del paso vertical y registra el recorrido en el log.
- UI: opción «Sigue al hablante» en Encuadre y slider «Posición en el plano» por speaker. Guardar speakers invalida los renders.
- Tests: `tests/test_focus.py` (recorrido, suavizado y render real con ffmpeg sobre un vídeo mitad rojo / mitad azul).
- ASD automático (como mymoviepy): `ASD_WORKER_URL` (worker TalkNet de `asd_worker/` del repo viejo, GPU). Con worker, el render corta el tramo (720 p, 25 fps), lo manda a `POST /asd` y usa `speakers[].center_norm` + `segments`; cacheado por clip en `asd_<start>_<end>.json`. Sin URL o si falla, usa los sliders de posición de los speakers. En 2026-10-19 el worker antiguo (192.168.1.46:8900) no respondía: sin probar contra un worker real.

## Mapas de países

- `app/data/countries-50m.json` (world-atlas 2.0.2, ISC; Natural Earth) + `app/services/country_maps.py`: PNG transparente del país en el rojo de marca, contorno crema y vecinos tenues; solo Pillow. 57 países (Europa entera + los que salen más en política), con recuadros que quitan ultramar (Francia, España, Noruega…).
- API: `GET /api/assets/maps/countries` y `POST /api/assets/maps {countries}` (crea assets `kind="map"` «Mapa de X», sin duplicar). UI: sección «Mapas de países» en la librería del panel de gráficos. Sirven como imagen en un gráfico o como objeto que orbita (Plantillas).
- Tests en `tests/test_assets_api.py` (todos los países renderizan).
- «Europa» (continente entero en rojo, vecinos tenues) en la lista de mapas; los anillos que cruzan el antimeridiano (Rusia) se desenvuelven.

## El planner pone los mapas de los países

- `country_maps.mentions(words, min_start)` reconoce países (nombres de varias palabras, alias como EEUU, y «Europa») en las palabras del clip. «europeos» no cuenta.
- `POST /api/clips/{id}/graphics-plan/suggest` crea en la librería los mapas que falten de los países nombrados (hasta 4; `services/map_library.py`) y el planner pone el mapa (`style original`) en la primera mención posterior al gancho (≥ 2,5 s), salvo que el modelo ya haya puesto esa imagen. El prompt del modelo también sabe qué son las imágenes «Mapa de X».
- Efecto secundario: sugerir gráficos puede añadir mapas a la librería del usuario.
- Arreglo (clip 42): los emojis caían sobre los subtítulos cuando la banda iba más abajo que el corte. `graphicZones` recibe ahora el borde inferior de la banda y coloca los gráficos debajo.

## Motivos nuevos: counter, strike, lower_third

- `fx_worker`: `motifs/counter.mjs` (cifra que rueda de `from_value` a `to_value` y se para en la palabra; pasos precalculados, números en español), `motifs/strike.mjs` (tarjeta tachada con aspa a rotulador, dos trazos de 0,22 s) y `motifs/lowerThird.mjs` (rótulo nombre + cargo). Contrato y registro actualizados; 99 tests.
- Backend: `GraphicIn` (campos `from_value`, `to_value`, `prefix`, `suffix`, `label`, `name`, `role`), programador (los tres son «grandes»; el contador entra 0,8 s antes) y planner (el modelo puede proponer `counter` y `strike`; el rótulo de nombre automático es el siguiente punto).
- Editor: botones «+ Contador», «+ Tachar», «+ Rótulo» y campos por tipo.
- Verificado con un render real de prueba (fotogramas en cada motivo).

## Rótulo de nombre automático

- `graphics_planner.speaker_beats`: al sugerir gráficos, cada speaker con nombre recibe un `lower_third` (nombre + cargo de su ficha) cuando empieza un turno de ≥ 1,5 s, tras el gancho (≥ 2,6 s). Prioridad 8, por encima de contadores y mapas; es editable como cualquier gráfico. Sin nombre en la ficha, no hay rótulo.

## @ del canal original y enlace en la descripción SEO

- `projects.source_handle` (migración 0008): el @ del canal de YouTube de donde viene el vídeo. Se rellena solo al ingerir (`uploader_id` de yt-dlp) y se edita en la pantalla del proyecto («Canal del vídeo original (@)»; acepta `esRadio`, `@esRadio` o la URL del canal). Los proyectos anteriores lo tienen vacío: se escribe a mano.
- «Generar SEO» antepone a la descripción `@canal` (lo primero, para etiquetarlo) y `Vídeo original: <enlace>` con `&t=` al segundo donde empieza el clip (enlace tal cual si no es de YouTube). No duplica lo que ya esté; lo que se guarda es lo que el usuario deja en el cuadro.
- Pantalla completa: la banda de subtítulos va bajo la parte nítida (`topH + 30…110`), ignorando los subtítulos quemados del original (el render ya no los detecta en este diseño). Gráficos debajo de la banda.

## F9 (parte 1): revisión automática y hoja de contactos

- Al acabar cada render (borrador y final) se genera `contact_<calidad>.jpg` (un fotograma cada 2,5 s en rejilla) y `qa_<calidad>.json` con comprobaciones (`app/services/qa.py`): duración = clip + cortinillas, audio (sin audio, casi mudo, pico > −0,1 dB), pantalla negra ≥ 1 s, gráficos grandes solapados, gráficos visibles < 0,8 s y gráficos descartados. Solo informan: nunca tumban el render.
- `GET /api/clips/{id}/qa` y bloque «Revisión automática» (✔/⚠/✖ + hoja de contactos) en el panel de render.
- Sin hacer (necesita visión por ordenador): gráfico sobre una cara, estilo de subtítulo que no corresponde al hablante, destellos < 0,3 s. Tampoco están el bucle notas → reglas ni los límites/borrado de media antigua.

## Tarjetas de clip: render, cola y subido

- `ClipOut` añade `render_job_status` (queued/running), `render_job_progress` y `upload_job_status`. Las tarjetas del proyecto muestran «En cola para renderizar», «Renderizando N %», «Subiendo a YouTube…», «Borrador/Final listo», fallos de render y de subida, y para un clip subido: fecha, privacidad y enlace «Ver en YouTube». La lista se refresca sola cada 3 s mientras haya algo en marcha.
- Cola: una subida a YouTube (solo red) ya no espera al render de su usuario (`max_concurrent_jobs` solo cuenta los jobs que no son de subida; máximo una subida a la vez por usuario). Antes, con límite 1, el clip 64 esperaba en cola «subiendo» detrás de los renders.

## Carriles de render configurables y pantalla de usuarios (admin)

- `RENDER_LANES` (por defecto 1) es el número de renders a la vez en todo el sistema (`queue.claim_next`); `FX_MAX_RENDERS` (compose lo toma de `RENDER_LANES`) es el tope de `fx_worker`. Regla 3 de `CLAUDE.md` reescrita. Con 2 carriles conviene `FX_WORKERS=1` y vigilar la RAM.
- Pantalla «Usuarios» (solo admin, `/admin`, `routers/admin.py`): por usuario, jobs a la vez (1–8), minutos máximos de vídeo y activo; muestra los jobs en marcha y en cola y los carriles del sistema.

## Motivo `puppets`: monigotes de comic de la mano con las caras

- `fx_worker/src/motifs/puppets.mjs`: 1–3 monigotes (`look` «southpark» por defecto: recortables de cabeza enorme con traje, abrigo o parka y brazos cortos que caminan balanceándose; o «stick»: de palo, trazo grueso con contorno crema) con la cara de una imagen de la librería como cabeza en círculo, cogidos de la mano; entran andando desde la izquierda (piernas que se balancean) y en la palabra dan un saltito. Se ajusta al hueco bajo la banda (escala 0,5–1,3). Contrato `images` (png, 1–3); `server.mjs` copia las caras como las de `image`.
- Backend: gráfico `puppets` con `asset_ids` (1–3 imágenes del usuario; el job las resuelve a rutas y descarta el gráfico si falta alguna); cuenta como «grande» en el programador y bloquea el borrado de sus imágenes. Editor: botón «+ Monigotes» y selector de caras por monigote.
- Verificado con un render real (fotogramas del paseo y del saltito).

## Pestaña «Imágenes»: editor de la librería

- Página `/images` (enlace «Imágenes» en el inicio): rejilla de la librería con subida (botón o arrastrar y soltar, varias a la vez), renombrar en la miniatura (Enter o al salir del campo), borrar y los mapas de países (`components/CountryMaps.tsx`, que sigue también en el panel de gráficos).
- Editor: quitar fondo con IA, voltear, girar (−180…180°), caja de recorte arrastrable con zoom y forma rectángulo/óvalo/círculo; «Guardar como copia» o «Reemplazar» (409 si la imagen se usa en gráficos o plantillas).
- Backend: `services/image_edit.py` (segmentación con onnxruntime y el modelo `u2net_human_seg` de rembg, ~170 MB, descargado a `MEDIA_DIR/_models` la primera vez; en lugar de la librería `rembg` completa, mucho más pesada) y `POST /api/assets/{id}/preview` y `/edit`. El resultado de quitar el fondo se cachea junto al asset (`N.nobg.png`) y se borra al reemplazar o borrar. Un candado evita dos usos del modelo a la vez.
- Probado en navegador contra el entorno local con una foto real: subida, quitar fondo, círculo, arrastre, copia y renombrado.

## Limpieza de disco: lo pesado se regenera

- Criterio del usuario: no se guarda nada que se pueda regenerar descargando el vídeo de nuevo. Se conservan `words.json`, `silences.json` y la BD (clips, gráficos, SEO, speakers); se borran el vídeo original, el audio y las carpetas `clip_*` (borrador, final, miniatura, análisis, hoja de contactos y revisión).
- `services/cleanup.py`: `usage`, `free_project` (no hace nada con un job activo; deja los clips en `render_state=none`) y `cleanup_old`. El worker la ejecuta cada hora para los proyectos sin ficheros nuevos en `MEDIA_RETENTION_DAYS` (por defecto 14; 0 = nunca).
- `services/source.py::ensure_source`: al renderizar (o re-transcribir) sin vídeo original, se descarga de nuevo con yt-dlp (el log lo dice); si falla, el render falla con «No se pudo descargar de nuevo el vídeo original». Con el vídeo borrado, `video-url` responde 409 y el reproductor se oculta con un aviso.
- API: `GET /api/storage` (libre/total del disco y tamaño por proyecto) y `POST /api/projects/{id}/free-space`. Pantalla Proyectos: columna «Disco», botón «Liberar X» y la línea de disco.
- Pendiente de mirar con datos reales: los vídeos largos tardan en bajar de nuevo (minutos) la primera vez que se renderiza tras una limpieza.
