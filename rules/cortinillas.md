# Cortinillas

- El short **arranca directamente en contenido**, con una intro corta del propio clip (por defecto ~4 s, entre 2,5 y 8 s), cortada en un silencio tras una frase completa. Motivo: los primeros segundos deciden la retención y no se gastan en una pantalla de marca. (Decidido el 2026-10-17.)
- La **cortinilla de inicio es opcional**: casilla por clip y valor por defecto en la plantilla de marca, apagada por defecto. Si está activada, entra después de la intro, **se inserta** (pausa el clip: audio y subtítulos se detienen, no se superpone) y dura 3,6 s.
- La **cortinilla final es siempre**, sin interruptor. Su barrido tapa el último fotograma compuesto y no vuelve a destapar el clip.
- Ninguna cortinilla pisa una palabra: la de inicio cae en un silencio tras una frase completa.
- Todo lo posterior a la cortinilla de inicio se desplaza con un único mapa de tiempos: `t_salida = t_origen + Σ duración de las cortinillas anteriores`. Se calcula en un solo sitio.
