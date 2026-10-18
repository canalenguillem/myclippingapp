// Blanco y negro del clip citado (speakers con is_source): un filtro CSS `grayscale()` sobre el contenedor del vídeo,
// animado con GSAP para entrar y salir. Se probó el tratamiento de color de HyperFrames (`data-color-grading`), pero
// usa WebGL y sin GPU (Chrome en modo software) un clip de 4 s no terminaba en 150 s; el filtro CSS añade ~0,6 s.
// El filtro va sobre un contenedor y no sobre el <video>, como recomienda HyperFrames para animar material de vídeo.

const PAD_BEFORE = 0.1;
const PAD_AFTER = 0.2;
const MERGE_GAP = 0.6;
const FADE = 0.2;

/** Tramos del clip en los que habla un speaker `is_source`, unidos si están a menos de 0,6 s. */
export function sourceIntervals(words, speakers, duration) {
  const spans = words
    .filter((w) => speakers[w.speaker]?.is_source && w.start < duration)
    .map((w) => [Math.max(0, w.start - PAD_BEFORE), Math.min(duration, w.end + PAD_AFTER)]);
  const merged = [];
  for (const [a, b] of spans) {
    const last = merged[merged.length - 1];
    if (last && a - last[1] <= MERGE_GAP) last[1] = Math.max(last[1], b);
    else merged.push([a, b]);
  }
  return merged;
}

const fmt = (n) => Number(n.toFixed(3));

export function treatmentLayer({ intervals, target = "#vwrap" }) {
  const script = intervals
    .map(([a, b]) => {
      const fade = Math.min(FADE, (b - a) / 2);
      return (
        `tl.fromTo("${target}",{filter:"grayscale(0)"},{filter:"grayscale(1)",duration:${fmt(fade)},ease:"power1.inOut"},${fmt(a)});` +
        `tl.to("${target}",{filter:"grayscale(0)",duration:${fmt(fade)},ease:"power1.inOut"},${fmt(b - fade)});`
      );
    })
    .join("\n");
  return { script };
}
