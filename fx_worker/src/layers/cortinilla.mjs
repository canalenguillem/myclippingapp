// Cortinilla de inicio: se INSERTA entre dos instantes del clip (el clip se pausa). En tiempo de salida ocupa
// [at, at + duration]. Barrido curvo con canto blanco que tapa el último fotograma (0,42 s), el color de marca
// mientras dura y barrido de salida que destapa el siguiente. Los fotogramas congelados los pone el builder.
// (El contenido de la plantilla —título, píldora que se dibuja, objeto que orbita— llega en el paso siguiente.)

export const SWEEP = 0.42;

const fmt = (n) => Number(n.toFixed(3));

export function cortinillaLayer({ at, duration, color }) {
  const sweepSvg = `<svg id="sweep" class="sweep" width="1560" height="1920" viewBox="0 0 1560 1920">
      <path d="M0 0 H1230 Q1560 960 1230 1920 H0 Z" fill="#fff" transform="translate(46 0)"/>
      <path d="M0 0 H1230 Q1560 960 1230 1920 H0 Z" fill="${color}"/>
    </svg>`;
  const html = `<div id="cort" class="clip" data-start="${fmt(at)}" data-duration="${fmt(duration)}" data-track-index="5">
    ${sweepSvg}
  </div>`;
  const css = `#cort{position:absolute;inset:0}
.sweep{position:absolute;left:0;top:0;will-change:transform}`;
  const script =
    `tl.fromTo("#sweep",{x:-1560},{x:0,duration:${SWEEP},ease:"power2.inOut"},${fmt(at)});` +
    `tl.to("#sweep",{x:1560,duration:${SWEEP},ease:"power2.inOut"},${fmt(at + duration - SWEEP)});`;
  return { html, css, script };
}
