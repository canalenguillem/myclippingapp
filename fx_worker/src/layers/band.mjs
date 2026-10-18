// Banda de papel rasgado (§7.1 del md): franja crema a todo el ancho que TAPA los subtítulos quemados del vídeo
// de origen. Los bordes rasgados salen de ruido 1D multiescala con semilla fija, así que son idénticos en cada render.
import { mulberry32 } from "../rng.mjs";

export const WIDTH = 1080;
export const TOOTH_MIN = 6; // el rasgado nunca se mete en la zona protegida: siempre sobresale al menos 6 px
export const TOOTH_MAX = 22;
export const ROOM = 30; // píxeles reservados por encima y por debajo de la zona protegida (dientes + canto blanco)
const RIM = 3; // canto blanco fibroso del desgarro
const STEPS = [[180, 7], [60, 4], [18, 2.2], [5, 1]]; // [paso en px, amplitud] del ruido (md §7.1)
const smooth = (t) => t * t * (3 - 2 * t);

function noise1d(seed, width) {
  const rng = mulberry32(seed);
  const out = new Float64Array(width + 1);
  for (const [step, amp] of STEPS) {
    const lattice = Array.from({ length: Math.ceil(width / step) + 2 }, () => rng() * 2 - 1);
    for (let x = 0; x <= width; x++) {
      const i = Math.floor(x / step);
      const f = smooth(x / step - i);
      out[x] += amp * 0.55 * (lattice[i] * (1 - f) + lattice[i + 1] * f);
    }
  }
  return out;
}

/** Cuánto sobresale el borde, por columna: siempre entre TOOTH_MIN y TOOTH_MAX. */
export function bandGeometry({ y0, y1, width = WIDTH, seed = 1 }) {
  const clamp = (v) => Math.min(TOOTH_MAX, Math.max(TOOTH_MIN, 14 + v));
  const up = Array.from(noise1d(seed, width), clamp);
  const down = Array.from(noise1d(seed + 1, width), clamp);
  return {
    top: up.map((out) => y0 - out), // y absoluta del borde superior en cada x
    bottom: down.map((out) => y1 + out), // y absoluta del borde inferior en cada x
  };
}

const f1 = (n) => Number(n.toFixed(1));

/** `core` = filas que la banda DEBE cubrir al 100 % (ya con su margen). */
export function bandLayer({ core, paper, seed = 7 }) {
  const { y0, y1 } = core;
  const geo = bandGeometry({ y0, y1, seed });
  const svgTop = y0 - ROOM;
  const height = y1 - y0 + 2 * ROOM;
  const xs = [];
  for (let x = 0; x < WIDTH; x += 6) xs.push(x);
  xs.push(WIDTH);
  const edge = (offset) => [
    ...xs.map((x) => `${x},${f1(geo.top[x] - svgTop - offset)}`),
    ...xs.slice().reverse().map((x) => `${x},${f1(geo.bottom[x] - svgTop + offset)}`),
  ].join(" ");

  // Fibras horizontales del papel (poca opacidad), con semilla fija.
  const rng = mulberry32(seed + 99);
  const fibers = Array.from({ length: 140 }, () => {
    const x = rng() * WIDTH;
    const y = ROOM + rng() * (y1 - y0);
    const len = 40 + rng() * 160;
    return `<line x1="${f1(x)}" y1="${f1(y)}" x2="${f1(x + len)}" y2="${f1(y + rng() * 2 - 1)}"/>`;
  }).join("");

  const html = `<svg id="band" width="${WIDTH}" height="${height}" viewBox="0 0 ${WIDTH} ${height}">
  <polygon points="${edge(RIM)}" fill="#FFFFFF"/>
  <polygon points="${edge(0)}" fill="${paper}"/>
  <g stroke="rgba(120,100,70,0.07)" stroke-width="1">${fibers}</g>
</svg>`;
  const css = `#band{position:absolute;left:0;top:${svgTop}px;filter:drop-shadow(0 4px 4px rgba(0,0,0,.4))}`;
  return { html, css, svgTop, height };
}
