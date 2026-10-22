- Todo fotograma que se extrae del clip para la composición (congelados bajo los barridos) se comprueba que existe: ffmpeg termina sin error y sin fichero si el instante cae pasado el final real del vídeo (el clip dura unas milésimas menos de lo pedido). El último fotograma se pide respecto al final real. Un render que cae al plan B por esto se ve como «Aviso: LintError… missing_local_asset» en el editor.

- Toda descripción de YouTube generada lleva el @ del canal original en la primera línea y el enlace al vídeo original (con el segundo del clip); sin el @ guardado en el proyecto, solo el enlace.

- Las caras de los monigotes se preparan en la pestaña «Imágenes»: quitar fondo y recorte en óvalo o círculo, de frente y con la cara centrada; una foto con el fondo sin quitar se recorta en círculo pero se ve peor.

- Un render de un proyecto limpiado tarda lo que la descarga del vídeo original más el render: el log del job debe decir «descargándolo de nuevo»; si YouTube ya no sirve el vídeo, el render falla con un mensaje claro (no se queda colgado).

- La publicación automática en YouTube solo sale si la revisión automática del render final no encuentra fallos (duración, audio, pantalla negra, gráficos solapados); con fallos se queda sin publicar y con el motivo a la vista. Público es una elección explícita del usuario clip a clip, nunca un valor por defecto de la app.

- Un render que cae al plan B de subtítulos (sin banda ni cortinillas) no es un render válido: no se publica solo y el clip muestra el aviso hasta que se vuelva a renderizar.
