# Cortinillas

- El short **arranca directamente en contenido**, con una intro corta del propio clip (por defecto ~4 s), cortada en un silencio tras una frase completa. Motivo: los primeros segundos deciden la retención y no se gastan en una pantalla de marca. (Decidido el 2026-10-17.)
- La **cortinilla de inicio es opcional**: casilla por clip y valor por defecto en la plantilla de marca, apagada por defecto. Si está activada, entra después de la intro (por defecto) y **se inserta** (pausa el clip: audio y subtítulos se detienen, no se superpone) y dura 3,6 s.
- **No hay máximo para la posición de la cortinilla de inicio**: puede ir en cualquier silencio tras una frase completa, también a mitad del clip, como en los ejemplos. La posición se ajusta por clip. (Decidido el 2026-10-18.)
- La **cortinilla final es siempre**, sin interruptor. Su barrido tapa el último fotograma compuesto y no vuelve a destapar el clip.
- Ninguna cortinilla pisa una palabra: la de inicio cae en un silencio tras una frase completa.
- Todo lo posterior a la cortinilla de inicio se desplaza con un único mapa de tiempos: `t_salida = t_origen + Σ duración de las cortinillas anteriores`. Se calcula en un solo sitio.
- La posición de la cortinilla de inicio se guarda en `clips.cortinilla_at` (segundo del clip, `NULL` = la elige el programador); al cambiar el recorte se resetea, porque es relativa al inicio. Los textos y colores de las cortinillas dependen del canal: viven en `brand_templates.cortinilla` y el usuario los edita en Plantillas.
- La cortinilla final se manda SIEMPRE (sin plantilla, con color de marca y botones por defecto). Si la de inicio está activada y no hay silencio válido, se omite con un aviso en `render_error`; el fallback ASS no lleva ninguna cortinilla y lo dice. La miniatura nunca cae dentro de una cortinilla.

- Ningún elemento gráfico lleva un color de marca escrito a fuego: todo (cortinillas, karaoke, gancho, tarjetas, contador, rótulo, tachado, chispas, corbata de los monigotes) usa el color de marca de la plantilla (`brand.primary`), y el naranja `#DA2E09` solo es el valor por defecto del preset `editorial` cuando no hay plantilla. Un motivo nuevo recibe `accent` y no puede usar un color de marca literal.
