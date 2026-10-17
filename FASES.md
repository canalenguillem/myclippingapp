# FASES — ajustes al plan F4–F9 para conseguir el estilo de los vídeos de referencia

Este documento **no sustituye** a `status.md` ni al plan de `~/.claude/plans/`. Mantiene su numeración y
solo añade lo que falta para llegar al estilo de los dos vídeos de ejemplo (urna/indultos/mapa y
Mínguez/muñecos/«posMontserrat»). Úsalo en Claude Code así: «haz F4 del plan aplicando los ajustes de FASES.md».

---

## Lo que el plan actual ya resuelve bien (no tocar)

- Una sola transcripción del vídeo entero y clips cortados de ella.
- `graphics_planner` = LLM + **programador determinista** que impone las reglas de sincronía. Es mejor que
  dejar que el LLM ponga los tiempos: el LLM elige qué motivo y en qué palabra; el código decide los frames.
- Portar `fx_worker` y `clip_detector` del repo viejo en lugar de reescribirlos.
- Layout `split` en `Clip`: es justo la composición de los vídeos (plano corto arriba, general abajo).

## Lo que falta, en una tabla

| Hueco | Por qué importa | Va en |
|---|---|---|
| **Diarización (speaker por palabra)** | Subtítulos con estilo distinto por interlocutor, rótulo cuando la persona está en plano, clip citado en B/N | F4 |
| **Carril de render global** | La cola limita por usuario, no por tipo. Con `WORKER_CONCURRENCY=2`, dos usuarios lanzan dos renders a la vez. El status dice «la cola serializa los renders», pero hoy no es así | F5 |
| **Zona segura sin caras** | Que ningún gráfico ni la banda tape caras | F5 |
| **Banda de papel + dos estilos de subtítulo** | Es la firma visual de los dos vídeos | F5 |
| **Cortinilla del canal (intro y outro)** | `pill_draw` con los tiempos exactos de §6, tapando y destapando el clip compuesto | F6 |
| **Librería de assets por usuario** | Urna, esposas, guante, caras… se reutilizan entre vídeos. Sin esto, cada vídeo es artesanía | F7 |
| **Motivos con objeto** | El catálogo de F7 es tipográfico (keyword, counter, strike…). Los vídeos viven de tarjeta-objeto, sello, romper, mapa que estalla, golpe y muñecos | F7 |
| **Bucle notas → reglas** | Lo que hace que cada vídeo salga mejor que el anterior | F9 |

---

## F4 Detección y revisión — añadir

```
Además de lo previsto en F4:
- transcription.py: speaker_labels=True en AssemblyAI; guarda "speaker" en cada palabra y genera
  "segments" por utterance {start, end, speaker, text}. Proyectos ya importados: si words.json no trae
  speaker, la UI lo indica y ofrece re-transcribir.
- Project.speakers JSON (migración): {"A": {"name": "", "role": "", "caption_style": "sans_upper",
  "is_source": false}}. is_source=true marca un clip citado (sale en B/N y con serif cursiva).
- La transcripción editable permite reasignar speaker a un rango de palabras, no solo corregir texto.
- clip_detector pide también "parts": partes temáticas del clip, una frase cada una (§4.1 del md).
  Sirven al planner de F7 para repartir los gráficos por tema.
- Silencios por RMS en ventanas de 50 ms (< -45 dB, §3.3): start/end del clip se ajustan al silencio
  más cercano (±0,6 s). Guarda los silencios del proyecto en silences.json; F7 los reutiliza.
- Sustituye el estado provisional "transcribed" por un Enum: downloading → transcribing → detecting
  → ready | failed.
```

**Hecho cuando:** cada palabra tiene speaker, puedes ponerles nombre, cargo y estilo, y los clips empiezan y acaban en silencio.

---

## F5 Render vertical — añadir

```
Además del porte de make_vertical_clip / render_clip / fx_client / fx_worker:
- Carril de render: limita los jobs "render" a 1 en todo el sistema (lock por tipo en claim_next
  o worker dedicado con su propia cola). Test que lo demuestre con dos usuarios.
- Análisis por clip (antes del render), sobre raw 540x960 a 5 fps (§3.4): cortes de plano,
  cajas de cara con mediapipe → "safe_zone" (franja horizontal sin caras) y subtítulos quemados
  (§3.2). Guarda clip_<id>/analysis.json.
- Capas nuevas en la composición de Remotion, con los valores del md:
  · PaperBand (§7.1): franja crema rasgada, opcional por preset. Si hay subtítulos quemados,
    obligatoria y tapándolos al 100 %.
  · Captions con dos estilos según Project.speakers: sans_upper (Inter ExtraBold, MAYÚSCULAS)
    y serif_italic (Cormorant SemiBold Italic). Karaoke rojo #DA2E09 con pop (§7.2).
  · Grayscale en los tramos de speakers con is_source=true.
- Curvas (§5) y paleta del ADN en un util compartido. El preset "editorial" = ADN del §5.
- Render en dos calidades: draft 540x960 para revisar, final 1080x1920 solo tras aprobar.
- Endpoint de stills: frames sueltos en tiempos dados, para validar sin render completo.
```

**Hecho cuando:** un clip sale con banda, subtítulos en dos estilos según quién habla y el clip citado en B/N. Dos renders lanzados a la vez se ejecutan uno detrás de otro.

---

## F6 Cortinillas — añadir

Decisión: **solo cortinilla del canal al principio y al final. Nada a mitad de clip.**
`cortinilla_test.mp4` es **solo un ejemplo de técnica**, no el diseño final. No sirve tal cual
porque arranca barriendo sobre un fotograma del vídeo: en un intro se vería el clip antes de la
cortinilla. Lo que se toma del ejemplo: barrido curvo con canto blanco, texto que entra
desenfocado, línea que dibuja una forma y objeto que orbita (§6). El diseño, el texto y los
colores son los del canal de cada usuario.

```
Además de lo previsto en F6:
- Cortinilla = plantilla de marca, no un vídeo fijo. Parámetros: título (palabra en serif cursiva
  opcional), antetítulo, logo o asset que orbita, color de fondo, duración (por defecto 3,6 s).
  Primera plantilla: pill_draw con los tiempos de §6. Diseñada para mi canal, no «Spain Facts».
- INTRO: el primer fotograma ya es cortinilla a pantalla completa en el color de marca. Prohibido
  que se vea ningún fotograma del clip antes de que termine. Solo al final, el barrido de salida
  destapa el primer fotograma del clip ya compuesto (con banda y subtítulos).
  Test: los fotogramas 0…(fin del barrido de salida − 0,42 s) no contienen píxeles del clip.
- OUTRO: el barrido de entrada tapa el último fotograma compuesto del clip y la cortinilla
  termina en el color de marca, en end_card o en cta_subscribe. No vuelve a destapar el clip.
- Audio: whoosh en cada barrido y brillo mientras se dibuja la línea (§10). La voz del clip no se
  pisa: el intro acaba antes de la primera palabra y el outro empieza después de la última.
- Desfase constante: todo lo del clip (subtítulos, beats) se desplaza la duración del intro menos
  el solape de la transición. Calcúlalo en un solo sitio; test de sincronía tras el intro.
- Intro y outro activables por clip (intro_enabled / outro_enabled ya existen en el modelo).
- Editor de la plantilla en la UI con previsualización (@remotion/player) para ajustarla sin render.
- Fuera del alcance: inserts a mitad de clip. No implementar.
```

**Hecho cuando:** un clip sale con la cortinilla de tu canal al principio y al final, en el intro no asoma ni un fotograma del clip antes de tiempo, y los subtítulos siguen en sincronía.

---

## F7 Gráficos por transcripción — añadir (lo más importante)

### F7a — Librería de assets (antes de los motivos)

```
- Modelo Asset (user_id, kind: object|face|logo|icon|map, name, tags, path, source, license_note).
- Subida manual + búsqueda: el planner pide "urna"; la UI busca candidatos y el usuario elige.
  La app nunca usa una imagen sin que el usuario la haya elegido o subido.
- Limpieza automática al guardar: quitar fondo (rembg), recortar al contenido, alfa limpio
  (erosión 1 px + blur 1,2, §9). Aviso si detecta marca de agua (pngtree, Dreamstime…).
- Tratamientos de estilo precalculados por asset: tarjeta de papel con sombra, icono de línea
  teñido de rojo, silueta. Esto es lo que hace que assets mediocres se vean del mismo estudio.
- Mapas de país desde world-atlas (§9), no desde imágenes.
- Assets reutilizables entre proyectos del mismo usuario.
```

### F7b — Motivos (además de keyword, counter, fact_card, strike, emoji, lower_third)

```
Motivos nuevos en fx_worker (§8 del md), cada uno con params tipados y descripción de una
línea para el catálogo que recibe el planner:
- object_card: asset en tarjeta de papel inclinada -5°, entra con pop.
- stamp: sello rojo que cae (escala 1,5→1 + back_out 2.2) sobre un object_card o una foto polaroid.
- break: el asset se parte en dos, mitades que giran ±9° y se separan, chispas con gravedad.
- map_shatter: mapa-bandera que se rompe en fragmentos Voronoi desde el punto de impacto.
- punch: objeto que entra con aceleración, impacta en la sílaba tónica, rebota; temblor del plano.
- puppets: cara recortada (asset face) sobre cuerpo de palo, dentro de la banda. Variantes: idle,
  bubble (bocadillo), music (notas), ring (cuerdas + guantes), laugh ("JAJA"), break.
- SFX sintetizados de §10 ligados a cada motivo.
Todos respetan safe_zone. El programador determinista rechaza un beat que no quepa.
```

### Ajustes al graphics_planner

```
- El LLM recibe: palabras del clip con speaker, parts, analysis.json, catálogo de motivos y
  lista de assets del usuario. Devuelve beats {anchor_word_index, motif, params, asset_ids}
  + missing_assets + verify.
- Si falta un asset, el beat queda en "pending_asset" y la UI lo pide; no se inventa.
- Opiniones atribuidas a quien habla; los datos objetivos (fechas, cargos) van a "verify" y la UI
  obliga a confirmarlos antes del render final (§4.3).
```

**Hecho cuando:** el planner propone «*indultos* → break con asset esposas, texto INDULTOS» y «*España?* → map_shatter + punch», tú lo apruebas en la timeline y sale así sin tocar código.

---

## F8 YouTube por usuario — sin cambios

---

## F9 QA y pulido — añadir

```
- Checks automáticos a 10 fps sobre el draft: gráfico sobre caja de cara, texto visible < 0,8 s,
  dos motivos grandes solapados, flash < 0,3 s, duración ≠ intro + clip + outro − solapes, pico de audio > 0,98,
  estilo de subtítulo que no corresponde al speaker. Informe con miniaturas de cada fallo.
- Notas por render: un job las aplica al plan (re-render draft) y propone el cambio de regla en
  rules/<area>.md (subtitulos, rotulos, cortinillas, plan, qa) para que el usuario lo acepte.
  Las reglas aceptadas entran en el prompt del planner en los siguientes vídeos.
- Marcar como fallido el proyecto cuando el job muere fuera del handler (ya en deuda técnica).
```

---

## Avisos

- **Las caras y objetos recortados son el cuello de botella real.** Prepara una carpeta de assets por personaje antes de F7b.
- **Sustituir logos comerciales en objetos** (el guante «EVERLAST» → «PSOE» del md) no debería ser una función automática de la app: es una herramienta para alterar marcas. A mano, para una pieza satírica concreta, es otra cosa.
- **Con políticos reales,** mantén la caricatura evidente y las citas atribuidas. Nada de voz sintética ni imagen manipulada que pueda pasar por real.
- **Licencia de Remotion:** ya está en tus riesgos. Si la app va a terceros de pago, presupuéstala antes de F7, que es donde más código Remotion vas a escribir.
