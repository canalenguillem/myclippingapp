# Conocimiento para automatizar vídeos con motion graphics

Base de conocimiento extraída de los proyectos hechos con Claude: Guillem, MiLogo, Loop, Referencias_Motion, MotajeClaude2 y el short del helado.

Sirve para diseñar una aplicación web que produzca este tipo de vídeos de forma automática. No decide el stack: describe **qué hay que hacer, en qué orden, con qué reglas y qué trampas evitar**. Los valores numéricos son los que funcionaron en producción.

Idioma de trabajo: español. Formato principal: vertical 9:16 (1080×1920, 30 fps); logos en 16:9 (1920×1080).

---

## 1. Tipos de pieza que la app debe cubrir

| Tipo | Entrada | Salida | Proyecto de referencia |
|---|---|---|---|
| **A. Vídeo de conversación «vestido»** | Vídeo grabado + transcripción con tiempos por palabra + imágenes de referencia | Vídeo con subtítulos nuevos, rótulos, gráficos sincronizados con palabras y cortinillas | Guillem |
| **B. Short explicativo con locución** | Guion/locución + fotos o clips propios | Vídeo 9:16 de 40–60 s en fases (problema → solución → cierre) | Helado |
| **C. Logo animado / ident** | Logo (PNG o fuente + texto), colores, frase | MP4 de 6–7 s con sonido + versión croma | Loop, MiLogo |
| **D. Biblioteca de estilo** | Vídeos de referencia | Catálogo de clips con fichas «cómo reproducirlo» | Referencias_Motion |

Todo se renderiza **por código** (fotograma a fotograma o con un motor HTML con línea de tiempo), sin generadores de vídeo por IA. La IA generativa de imagen solo se usa para crear recursos que faltan.

---

## 2. Flujo general (cualquier pieza)

1. **Ingesta**: vídeo, audio, transcripción, imágenes y fuentes.
2. **Análisis automático** del vídeo y la transcripción (§3).
3. **Guion de montaje** (la «historia»): partes, momentos clave y qué gráfico corresponde a cada palabra (§4).
4. **Preparación de recursos**: limpiar marcas de agua y logos de marca, recortar, vectorizar, generar lo que falte (§9).
5. **Render de pruebas**: fotogramas sueltos en momentos clave y una hoja de contactos, para aprobar antes del render completo.
6. **Render completo**: vídeo mudo + mezcla de audio por separado → unión final.
7. **Control de calidad** automático y visual (§11).
8. **Entrega**: MP4 con nombre versionado (`_v1`, `_v2`…) en la carpeta del proyecto.

Regla de trabajo con el usuario: enseñar **pruebas pequeñas primero** (la cortinilla, la banda, un subtítulo) y pedir aprobación. Después montar todo. No rehacer lo ya aprobado sin que lo pida.

---

## 3. Análisis automático del vídeo

### 3.1 Transcripción
Formato que usamos (JSON):
```json
{ "language": "es", "text": "...",
  "segments": [{"start": 0.24, "end": 2.4, "text": "..."}],
  "words":    [{"text": "De", "start": 0.24, "end": 0.32, "confidence": 0.988}] }
```
- Las transcripciones automáticas fallan en frases clave («rompieron» en lugar de «jodieron»). La app debe **dejar que el usuario corrija** el texto y conservar los tiempos.
- Hay tramos con voz que no aparecen transcritos (interjecciones). Compararlo con el análisis de audio (§3.3) y avisar.
- Los límites de segmento a veces no cuadran con el audio. Para cortar, manda el audio.

### 3.2 Estructura de la imagen
- Detectar **composiciones partidas**. Guillem: arriba plano corto (y 0–1342), abajo plano general (y 1342–1920).
  - Método: buscar la fila con salto de contenido constante en todos los fotogramas.
- Detectar **cortes de plano** dentro de cada zona: diferencia media absoluta entre fotogramas consecutivos a baja resolución (540×960, 5 fps).
  - Un pico por encima de ~18 sobre 255 es un corte.
  - Da los momentos en que cambia quién sale en el plano corto.
- Saber **quién está en plano** en cada tramo: combinar cortes con una hoja de contactos (fácil de revisar), o clasificar con reconocimiento facial o de vestuario.
  - Media de color de una zona fija: **no fue fiable**.
- Detectar **subtítulos quemados** (por ejemplo, verde y blanco con contorno).
  - Máscara de color: verde = G>200, R<90, B<90; blanco puro = min(RGB)>235 dentro de la franja.
  - Acumular en todo el clip → filas mín./máx. Guillem: y 1428–1494.

### 3.3 Audio
- RMS en ventanas de 50 ms → **silencios** (< −45 dB) para colocar cortes e inserciones sin pisar palabras.
- Ventanas de 0,5 s dan una vista general. Para el punto exacto de corte, usar 50 ms.

### 3.4 Clips de baja resolución para análisis
Decodificar una vez a 540×960 a 5 fps en un raw (`ffmpeg -vf fps=5,scale=540:960 -f rawvideo -pix_fmt rgb24`). Todas las mediciones se hacen sobre ese array: es muy rápido.

---

## 4. La historia: cómo convertir una conversación en guion de montaje

### 4.1 Partes y temas
- Dividir la transcripción en **partes temáticas**: intro / argumento de A / pregunta / argumento de B.
- Cada cambio de tema es candidato a **cortinilla insertada** (§6).
- En Guillem, el usuario definió el hilo: «cada interlocutor narra por qué dejó de votar al PSOE»:
  1. Por los indultos.
  2. «Jodieron España».
  
  La app debe permitir **escribir el hilo en una frase por parte**; de ahí salen los motivos gráficos.

### 4.2 Palabras gancho → gráficos
Cada motivo gráfico se ancla a **palabras concretas** (tiempos de `words`). Ejemplo real:

| Palabra (tiempo de origen) | Acción gráfica |
|---|---|
| «PSOE» 11.36 | El logo cae con golpe sobre la urna |
| «dejé de votar» 12.12 | Aspa roja a rotulador sobre la urna (dos trazos, 0,22 s cada uno) |
| «indultos» 13.80 | Panel rojo «INDULTOS»; las esposas se rompen a las 14.0 + chispas |
| «jodieron… España?» 21.48–22.48 | Mapa-bandera entra; el guante golpea justo en «España?»; el mapa se rompe en pedazos y el plano tiembla |
| «me echaron» 35.3 | Tarjeta de dato verificable |
| Primera aparición en plano de cada persona | Rótulo nombre + cargo |

Reglas de sincronía:
- La **acción fuerte** (golpe, rotura, aspa) cae **en la sílaba tónica** de la palabra gancho.
- La entrada del elemento se adelanta 0,3–0,8 s.
- Cada elemento vive 2–4 s; nunca dos elementos grandes a la vez.
- Salida antes del siguiente tema o de un cambio de plano importante.
- Los rótulos aparecen cuando la persona **está en el plano corto**, no cuando habla otra.

### 4.3 Contenido político o sensible
- Opiniones entre comillas «» y atribuidas a quien habla. Los gráficos ilustran **lo que dice**; no añaden juicios propios.
- Datos objetivos en tono neutro y verificables, por ejemplo «Procés · junio de 2021» o «PSOE de Madrid · destituido como líder · feb. 2015».
  - La app debe marcar estos datos como **pendientes de verificar** por el usuario.
- Evitar fotos de stock con marca de agua y marcas comerciales (sustituir el logotipo; ver §9).

### 4.4 Short explicativo en fases (tipo helado)
- Estructura para 40–60 s en 9:16:
  1. **Problema** (el dolor del espectador).
  2. **Solución** (ingredientes en foto fija, con las cantidades exactas).
  3. **Por qué funciona**, explicado con la imagen.
  4. **Despedida** con llamada a la acción.
- **La locución manda**:
  - Primero se cierra el texto locutado; el montaje se hace sobre la locución grabada.
  - No reescribir el guion una y otra vez.
  - Entregar el texto en **líneas cortas legibles en el móvil**.
- **Dar el dato con precisión** (gramos, mililitros, tiempos): es lo que da credibilidad.
- Las cantidades van en un recurso gráfico (ingredientes dando vueltas, tarjetas con cifras).
- Comprobar las limitaciones reales del producto o receta (por ejemplo, la heladera admite máx. 700 ml → receta para 0,5 L). Si falta un ingrediente en el guion, avisarlo.

---

## 5. Sistema visual (ADN de estilo)

Sacado de `Referencias_Motion/catalogo.json` (39 referencias):

- **Paleta**:
  - acento rojo `#DA2E09`
  - blanco `#FFFFFF`
  - gris claro `#E8E8E8`
  - negro `#0B0B0B`
  - papel/crema `#F3EEE2` (≈0.955, 0.935, 0.885)
  - tinta de texto `#1D1A17`
- **Tipografía**:
  - Sans geométrica muy negrita: Inter ExtraBold.
  - La palabra clave en **serif cursiva**: Cormorant SemiBold Italic.
  - Antetítulos en monoespaciada negrita pequeña con mucho espaciado (DejaVu Sans Mono Bold, tracking 5–9 px, en MAYÚSCULAS).
- **Ritmo**: escenas de 2–5 s; cada idea, una tarjeta; los cambios se sincronizan con palabras.
- **Recursos**:
  - Entradas y salidas desenfoque→nítido.
  - Tarjetas con esquinas redondeadas (radio 10–26 px) y sombra suave (blur 12–18, desplazada 8–14 px hacia abajo, opacidad 0,3–0,4).
  - Cortinillas rojas.
  - Subtítulos palabra a palabra.
  - Contadores en rodillo.
- **Prohibido en este estilo** salvo petición: destellos, estelas de luz, explosiones de partículas, giros 3D, degradados.

### Curvas de animación usadas
```python
ease_out_cubic(u) = 1 - (1-u)**3          # entradas
ease_in_cubic(u)  = u**3                  # salidas
smoothstep(u)     = u*u*(3-2u)
back_out(u, s=1.7): u-=1; return u*u*((s+1)*u+s)+1   # «pop» con rebote (s 2.0–2.2 para golpes)
```
- Entrada típica de tarjeta: back_out en 0,4–0,45 s, escala 0,55→1, desplazamiento +30–50 px→0 y opacidad 0→1 en 0,12–0,15 s.
- Salida: ease_in en 0,3 s (escala ×0,7 o deslizamiento fuera + fundido).

---

## 6. Cortinilla insertada «Spain Facts» (estilo G07, píldora que se dibuja)

**Concepto**: la cortinilla **pausa** el vídeo. Se inserta entre dos fotogramas de origen; imagen y audio se detienen y continúan después. Dura 3,6 s.

Línea de tiempo (s, relativo a la cortinilla):

| t | Acción |
|---|---|
| 0–0,42 | **Barrido** sobre el último fotograma: panel rojo con frente curvo (parábola, 260 px de flecha) y canto blanco de 46 px delante; izquierda→derecha |
| 0,30 / 0,48 | «Spain» (sans 116 px) y «*Facts*» (serif cursiva 138 px) entran desenfocados (blur 14→0) subiendo 24 px, ease_out 0,45 s |
| 0,55–1,50 | La línea blanca (4 px) **dibuja la píldora** (900×300, radio = alto/2) desde arriba-centro en sentido horario; marca vertical en el punto de arranque |
| 0,95 | Tarjeta blanca con el **mapa de España** rojo y «ESPAÑA» aparece con pop y **orbita por la píldora** (0,30 vueltas/s), siempre derecha, con sombra |
| 1,55 | Antetítulo «ESPAÑA EN DATOS» (mono 26 px, tracking 9) entra con blur |
| 2,75–3,35 | La cola de la línea persigue a la cabeza (la píldora se «desdibuja»); textos y tarjeta salen con desenfoque |
| 3,18–3,60 | Barrido de salida: el rojo se va y descubre el siguiente fotograma, con el mismo canto blanco |

Implementación de la píldora: recorrido parametrizado por longitud de arco (tramo recto superior derecho → semicírculo derecho → recto inferior → semicírculo izquierdo → recto superior izquierdo). Dibujar el subtramo [cola, cabeza] como polilínea antialias.

Parámetros a exponer: texto principal (2 palabras, la 2.ª en cursiva), antetítulo, objeto orbitante (imagen), color de fondo, duración.

Colocación: en un **silencio** entre temas. Guillem: fotogramas de origen 168 (5,60 s) y 539 (17,97 s).

---

## 7. Capas sobre el vídeo de conversación

Orden de composición por fotograma:

1. Fotograma de origen.
2. Rótulos, motivos gráficos y tarjetas de dato.
3. Temblor de cámara, solo en la zona del plano corto: escala 1,02 + desplazamiento amortiguado `18·e^(−dt/0.09)·cos(70·dt)` px.
4. Banda de papel.
5. Subtítulos.

Todas las capas en RGBA **premultiplicado** (float 0..1). Componer con `dst = src + dst·(1−αsrc)`. Escala, rotación y opacidad con una transformación afín sobre el recorte del elemento: no tocar el cuadro entero, así es rápido.

### 7.1 Banda de papel rasgado (tapa subtítulos quemados)
- Franja de papel crema a todo el ancho que **tapa las filas de los subtítulos quemados en todos los fotogramas**:
  - margen ≥ 8–10 px sobre la zona medida.
  - Guillem: núcleo 1419–1509, dientes del rasgado entre 1398 y 1524.
- Bordes:
  - Ruido 1D multiescala: pasos 180/60/18/5 px con amplitudes 7/4/2,2/1 ×0,55, más una leve inclinación.
  - Recortar con `clip` para que **nunca** descubra la zona protegida.
- **Canto blanco fibroso** de 2–8 px a lo largo del desgarro (el núcleo del papel); sombra interior junto al desgarro.
- Textura del papel:
  - ruido 2D en 3 escalas (±3–6 %);
  - fibras horizontales (ruido con blur anisótropo σx=5, σy=0,5);
  - un pliegue diagonal suave.
- Sombra proyectada: blur 4, desplazada 4 px, opacidad 0,4. Si es mayor, tapa cabezas.
- **Verificación automática**: α de la banda = 1 en todos los píxeles que fueron subtítulo en cualquier fotograma.
- Lección: se pidió estrecharla para **no tapar cabezas** del plano general. Si el subtítulo quemado cae sobre una cara (zoom), no hay solución sin repintado: avisar al usuario.
- Supermuestreo ×3 para que el borde quede fino.

### 7.2 Subtítulos nuevos (sobre la banda)
- Inter ExtraBold 64 px, **MAYÚSCULAS**, tinta `#1D1A17`, centrados en la banda (y≈1462). Ancho máximo 960 px; si no cabe, se reduce la escala.
- **Karaoke**: la palabra que suena en rojo `#DA2E09` con un pequeño pop (×1,05 que decae en 0,15 s). Las palabras aún no dichas, al 38 % de opacidad.
- Agrupar palabras en líneas:
  - corte tras puntuación (`.,?!;:`);
  - silencio > 0,35 s;
  - máximo 4 palabras o ~22 caracteres.
- Cada grupo aparece en `start − 0,04` y desaparece en `end + 0,25` (o al empezar el siguiente). Entrada: opacidad + subida de 6 px en 0,14 s.
- Separación entre palabras: 0,36 × tamaño. Con menos, el pop solapa palabras.

### 7.3 Rótulos (lower thirds)
- Posición: abajo a la izquierda **del plano corto** (x 48, y 1180), por encima del límite de la composición partida.
- Barra roja vertical de 12 px, que crece desde el centro en 0,25 s.
- Panel blanco redondeado que se despliega de izquierda a derecha en 0,4 s.
- Nombre en Inter ExtraBold 50 + cargo en mono 25 px, MAYÚSCULAS, rojo, tracking 5. El texto sube 26 px dentro del panel, recortado por él.
- Salida inversa en 0,35 s. Duración 2–3,5 s.
- Formato del dato: «J. Soto Ivars · periodista», «Tomás Gómez · expolítico».

### 7.4 Tarjeta de dato
Tarjeta papel crema, barra roja a la izquierda, antetítulo mono rojo + frase en Inter Bold 42. Entra con back_out desde abajo y sale con fundido.

---

## 8. Biblioteca de motivos gráficos (reutilizables)

| Motivo | Cómo se hace |
|---|---|
| **Tarjeta-objeto** (urna) | Imagen recortada (con alfa) sobre tarjeta de papel redondeada 380×420, inclinada −5°, entra con pop |
| **Sello que cae** (logo) | Escala 1,5→1 en 0,12 s + rebote back_out(2.2); sonido de golpe sordo |
| **Aspa a rotulador** | Dos trazos diagonales hechos con discos de radio variable (más gruesos en el centro), borde irregular con ruido. Se revelan a lo largo de su diagonal en 0,22 s cada uno, separados 0,28 s; sonido de rotulador |
| **Romper** (esposas) | Icono partido por la mitad; cada mitad gira ±9° desde su base y se separa 34 px (ease_out 0,45 s); 9 chispas con gravedad; título que sube; sonido metálico + crujido |
| **Mapa que se rompe** | Silueta → contorno blanco 7 px + relleno con franjas de bandera (1:2:1, borde de franja ondulado). Fragmentos Voronoi con semillas concentradas cerca del impacto; cada fragmento sale con velocidad radial (más rápido cuanto más cerca), giro, gravedad 900 px/s² y fundido a partir de 0,55 s. Anillo de onda expansiva 0,18 s |
| **Golpe con guante** | Entra desde fuera del cuadro con aceleración (u²) en 0,32 s, impacta en la palabra, rebota 60 px y sale. En el impacto: temblor + golpe grave + crujido |
| **Objeto orbitando un camino** | Posición por longitud de arco sobre un trazado; el objeto no rota |

Cada motivo es una función `dibuja(frame, t)` con sus tiempos de origen. La app puede ofrecerlos como **plantillas parametrizables**: imagen, texto, palabra gancho y posición.

---

## 9. Recursos: preparar, limpiar y generar

- **Siluetas de países**: usar datos abiertos (npm `world-atlas` 10m + `topojson-client`; España = id `724`), no imágenes de stock.
  - Proyección equirectangular con `cos(40°)` en longitud.
  - Excluir polígonos por latitud: Canarias (< 30°N) y Ceuta/Melilla (máx. < 36,3°N) si el mapa es pequeño.
- **Marcas de agua** (pngtree, Dreamstime): no usar. Rehacer el recurso por código (bandera a brocha, mapa) o generarlo.
- **Logos comerciales en objetos** (guante «EVERLAST» → «PSOE»):
  1. Máscara del texto: píxeles claros con baja saturación en la zona del logo, dilatada 11 px.
  2. `cv2.inpaint` Telea, radio 21, a ×3 de resolución, más un suavizado local.
  3. Escribir el texto nuevo en una serif condensada negrita blanco hueso, con arco leve y modulado por la luz del cuero (normalizar la luz **dentro de la zona del objeto**, no de toda la imagen).
- **Fondos blancos → alfa**: componentes conexas de píxeles casi blancos que tocan el borde; erosión 1 px + blur 1,2.
- **Iconos de línea** (blanco y negro): alfa = 1 − luminancia, recortar al contenido y teñir del color deseado.
- **Recursos que faltan**: generarlos con IA de imagen. En los prompts escritos para el usuario, referenciar siempre las imágenes adjuntas como `@image1`, `@image2`…
- Fuentes: si Google Fonts está bloqueado, usar paquetes npm `@fontsource/*` (woff2). Para cargarlas en Python/PIL: convertir woff2→ttf con `fontTools` + `brotli`.

---

## 10. Audio

- **Montaje con pausas**: cortar el audio original en los puntos de inserción, con fundidos de 12 ms en cada corte. Durante la cortinilla, silencio + efectos.
- **Mapa de tiempos** origen → salida: `t_sal = t_orig + Σ duración de cortinillas anteriores`. Todo efecto ligado a una palabra usa este mapa.
- **Efectos sintetizados** (sin bancos de sonido), a 48 kHz:
  - *whoosh*: ruido con paso banda que sube (o baja) de 400 a 6000 Hz, envolvente sen^1,5.
  - *pop*: seno con leve caída de tono y decaimiento de 25 ms.
  - *golpe*: ruido paso bajo 180 Hz con decaimiento de 70 ms + seno de 55 Hz.
  - *crujido*: 20–25 clics de ruido paso banda 1,5–9 kHz repartidos en 0,25 s.
  - *metal*: 4 parciales inarmónicos (1480, 2310, 3570, 5120 Hz) con decaimientos de 80–250 ms.
  - *rotulador*: ruido paso banda 1,2–6 kHz con envolvente de media senoide.
  - *brillo* de trazo: ruido agudo 3–9 kHz muy bajo mientras se dibuja una línea.
- Niveles: efectos ~−6 dB por debajo de su ganancia nominal, **siempre por debajo de la voz**; normalizar el pico final a 0,98.
- **Sonido ligado al render**: guardar los eventos del dibujo (por ejemplo, cada estampa del pincel con tiempo, radio y carga) y generar el sonido a partir de ellos.
  - Densidad de estampas = velocidad → volumen del roce.
  - Radio × carga = presión.
  - Inicios de trazo → toque de apoyo.
- Ambiente de sala muy bajo para que el silencio no suene digital; reverberación corta (IR de ruido con decaimiento de 70 ms al 2 %).

---

## 11. Control de calidad (automatizable)

- **Hojas de contactos**: rejilla de fotogramas en momentos clave (o uno cada 2,5 s del vídeo final). Es la herramienta de revisión principal, para la IA y para el usuario.
- **Fotogramas a tamaño completo** en los picos de acción (impacto, rotura, cortinilla a mitad).
- **Comprobaciones numéricas**:
  - La banda cubre el 100 % de los píxeles de subtítulo quemado.
  - Duración final = origen + cortinillas.
  - Audio sin saturación.
- **Revisión de motion designer** en al menos 3 rondas para piezas de marca (logos): crítica → arreglar → repetir. Mirar:
  - costuras de 1 px;
  - quietud real del final;
  - centrado exacto;
  - tiempos con la voz.
- Errores ya vistos:
  - Mezcla en modo *screen* hecha en YUV → color magenta. Forzar `format=gbrp`.
  - Consola Windows cp1252 → `UnicodeEncodeError`. Usar `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`.
  - `cv2.putText` sobre imagen float falla; usar uint8.
  - Escribir varios niveles anidados con tiempos propios en HyperFrames da error de lint. Los tiempos van en el elemento interior, con `id`.

---

## 12. Logo animado a pincel (MiLogo)

Objetivo: el logo («@xMx», fuente Chiller, rojo `#FF0000`) se **pinta a brocha** sobre pergamino; después se escribe la frase («AI Animation Experiences with Soul», serif cursiva marrón). 1920×1080, 7 s, sonido natural.

1. **Pergamino procedural**:
   - Tono base tomado de una foto de referencia (mediana de la zona central).
   - Ruido multiescala, fibras horizontales y manchas de humedad.
   - Bordes quemados irregulares hacia `#3B210F`, viñeta suave.
2. **Del glifo a trazos**:
   - Máscara del texto (desde fuente TTF o desde PNG).
   - Esqueleto (`skimage.skeletonize`) + transformada de distancia, que da el radio local.
   - Seguir el esqueleto como polilíneas:
     - **zonas de cruce** (±3 px alrededor de uniones) que se pueden atravesar varias veces;
     - prohibido dar media vuelta;
     - empezar por extremos;
     - ordenar de izquierda a derecha como escribiría una mano;
     - los puntos/gotas son trazos de 2 puntos.
   - Suavizar (σ=2) y remuestrear cada 1,5 px.
3. **Pincel de cerdas**:
   - 26 cerdas con posición, grosor y umbral de sequedad propios.
   - Cada paso estampa un círculo por cerda (antialias con `shift=2`).
   - Presión: entra y sale en punta.
   - Carga de tinta 1,25→0,4 a lo largo del trazo: las cerdas «secas» dejan de pintar → trazo seco.
   - Velocidad con ease-in-out y pausas de 0,07 s entre trazos.
   - El tiempo de cada trazo es proporcional a su longitud.
4. **Acabado**:
   - El grano del papel modula la absorción (huecos en zonas con poca tinta).
   - Acumulación en el borde (charco).
   - Tinta multiplicada sobre el papel.
   - Recortar a la silueta dilatada con borde de ruido (el pincel desborda un poco).
5. **Frase**: revelado de izquierda a derecha con frente ruidoso.
6. **Final quieto**: imagen fija desde 5,9 s.
7. **Versión croma**: el fondo es un color plano que no esté en la marca. La tinta se sigue tiñendo con la textura del papel.
8. **Sonido** desde los eventos de las estampas (§10):
   - pergamino que se coloca (roce + crujidos + golpe sordo a 0,42 s);
   - roce de cerdas;
   - toques de apoyo;
   - plumilla para la frase.

## 13. Logo «línea que se convierte en logo» (Loop, HyperFrames)

- Una sola línea monolínea (grosor fijo, puntas redondas) viaja por el encuadre, vuelve y **se convierte en el logo**.
  - Donde dibuja letras deja tinta.
  - Los enlaces se recogen detrás de la punta: sin fundidos ni escalados.
- Geometría con líneas, arcos y curvas de Hermite, siempre con **continuidad de tangente**.
- El último tramo de tinta cierra el logo, con clic, un pequeño rebote de la punta y un leve hundimiento del logo.
- Encaje: ancho ≈ 1/3 del cuadro, centro exacto (960, 540).
- Desenfoque de movimiento real, frase que se escribe, sonido sintetizado (lápiz, clic, nota grave) y versión croma (`#00FF00`, o `#0000FF` si la marca tiene verdes: las MP4 no guardan alfa y CapCut no maneja bien la transparencia).
- Render a 60 fps desde HTML con línea de tiempo (GSAP en local, sin CDN).
- Revisión con snapshots cada 0,25 s.
- Costuras de 1 px donde la línea se cruza: se resuelven dibujando por piezas solapadas + discos en los vértices.

## 14. Biblioteca de referencias de estilo (Referencias_Motion)

- Cortar un vídeo de ejemplos en clips (G = gráficos, T = transiciones/cortinillas, M = movimientos) con su miniatura.
- Ficha por clip: qué pasa, frase dicha, técnica, **cómo reproducirlo** y etiquetas.
- `catalogo.html` local para ver los clips, marcar favoritos y anotar (exporta `notas_referencias.json`).
- El usuario pide por código: «apertura como G01, cortinilla como G14, contadores como M08».
- La app debería tener este catálogo como **galería de plantillas**, cada una enlazada a su implementación.

Referencias más útiles:
- G07: píldora que se dibuja + objeto que orbita.
- G10/G15/G18/G20: subtítulos con palabra clave.
- G14/T05/T07: cortinillas de capítulo rojas.
- M01: panel que entra desenfocado.
- M08: contador en rodillo.
- M09: tachado.
- G19: datos con fuente verificada.
- G08: contador + caída con gravedad.

---

## 15. Rendimiento y escala

- Componer **solo en recortes** (ROI) de cada elemento; el cuadro completo, solo para la banda y el temblor.
- 1080×1920, ~1550 fotogramas: ≈ 6–8 min en CPU con numpy/OpenCV; fotogramas de prueba en segundos.
- Decodificar el origen en flujo (pipe de ffmpeg) y codificar en flujo (`libx264 -crf 16–17 -pix_fmt yuv420p`).
- Para las cortinillas, el fotograma anterior es el último compuesto (con banda y subtítulos) y el siguiente es el primero compuesto del tramo nuevo.
- Precalcular todo lo estático: banda, tarjetas, máscaras de texto (caché por texto + fuente + tamaño), fragmentos del mapa.
- Audio y vídeo por separado; unirlos al final (`-c:v copy -c:a aac 192k -shortest`).

## 16. Lo que la app debe pedir al usuario (formulario mínimo)

1. Vídeo original (y si lleva subtítulos quemados: sí/no; la app los detecta).
2. Transcripción con tiempos por palabra, **editable**.
3. Nombres y cargos de cada persona (y la app propone cuándo aparece cada una).
4. Hilo narrativo: una frase por parte.
5. Imágenes de referencia por motivo; la app avisa de marcas de agua y logos comerciales.
6. Texto de la cortinilla y objeto orbitante; si pausa el vídeo (por defecto sí).
7. Paleta y fuentes (por defecto, el ADN del §5).
8. Datos objetivos a mostrar, marcados como «pendiente de verificar».

Salida: pruebas para aprobar → vídeo `_v1` → cambios → `_v2`…
