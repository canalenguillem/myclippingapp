// Efectos que deshacen un elemento (§8 del md): `vaporize` (se descompone en fragmentos que salen volando como polvo) y
// `break` (se parte en dos mitades que giran y caen, con chispas). El elemento se construye ya partido: una rejilla de
// «teselas» (cada una con una copia del contenido desplazada y recortada) o dos mitades, y GSAP las mueve. Todo
// determinista: las velocidades salen de un generador con semilla (nada de Math.random()).
import { mulberry32 } from "../rng.mjs";

const fmt = (n) => Number(n.toFixed(3));

/** Contenido repartido en cols × rows teselas del mismo tamaño. `inner` es el HTML del contenido (w × h). */
export function tilesHtml({ id, inner, w, h, cols, rows }) {
  const tw = w / cols;
  const th = h / rows;
  const cells = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      cells.push(
        `<div id="${id}v${r * cols + c}" class="vt" style="left:${fmt(c * tw)}px;top:${fmt(r * th)}px;width:${fmt(tw + 0.5)}px;height:${fmt(th + 0.5)}px"><div class="vi" style="left:${-fmt(c * tw)}px;top:${-fmt(r * th)}px;width:${w}px;height:${h}px">${inner}</div></div>`,
      );
    }
  }
  return cells.join("");
}

export const TILES_CSS = `.vt{position:absolute;overflow:hidden}.vi{position:absolute}`;

/** Vaporizar: una onda de izquierda a derecha; cada tesela sale arriba y a la derecha, gira, se desenfoca y se desvanece. */
export function vaporizeScript({ id, cols, rows, at, seed = 1 }) {
  const rand = mulberry32(seed * 7919 + 13);
  const parts = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const idx = r * cols + c;
      const delay = (c / Math.max(1, cols - 1)) * 0.45 + rand() * 0.15;
      const dx = 50 + rand() * 230;
      const dy = -(20 + rand() * 210);
      const rot = (rand() - 0.5) * 200;
      const dur = 0.8 + rand() * 0.5;
      parts.push(`tl.to("#${id}v${idx}",{x:${fmt(dx)},y:${fmt(dy)},rotation:${fmt(rot)},opacity:0,filter:"blur(7px)",duration:${fmt(dur)},ease:"power2.in"},${fmt(at + delay)});`);
    }
  }
  return parts.join("");
}

/** Partir en dos: cada mitad gira ±9° desde su base y se separa 34 px (ease_out 0,45 s); después caen y se desvanecen. */
export function breakHtml({ id, inner, w, h }) {
  const half = w / 2;
  const side = (key, left, offset) =>
    `<div id="${id}${key}" class="vt" style="left:${left}px;top:0;width:${half}px;height:${h}px"><div class="vi" style="left:${offset}px;top:0;width:${w}px;height:${h}px">${inner}</div></div>`;
  return side("L", 0, 0) + side("R", half, -half);
}

export function breakScript({ id, w, h, at, seed = 1 }) {
  const rand = mulberry32(seed * 104729 + 5);
  const parts = [
    `tl.set("#${id}L",{transformOrigin:"0% 100%"},${fmt(at)});tl.set("#${id}R",{transformOrigin:"100% 100%"},${fmt(at)});`,
    `tl.to("#${id}L",{rotation:-9,x:-34,duration:0.45,ease:"power3.out"},${fmt(at)});`,
    `tl.to("#${id}R",{rotation:9,x:34,duration:0.45,ease:"power3.out"},${fmt(at)});`,
    `tl.to("#${id}L",{y:${fmt(h * 0.9)},rotation:-22,opacity:0,duration:0.55,ease:"power2.in"},${fmt(at + 0.5)});`,
    `tl.to("#${id}R",{y:${fmt(h * 0.9)},rotation:22,opacity:0,duration:0.55,ease:"power2.in"},${fmt(at + 0.5)});`,
  ];
  // chispas: puntitos que salen del corte con velocidad radial y gravedad (x lineal, y acelerada)
  for (let i = 0; i < 9; i++) {
    const a = -Math.PI / 2 + (rand() - 0.5) * 2.4;
    const speed = 160 + rand() * 220;
    const vx = Math.cos(a) * speed;
    const vy = Math.sin(a) * speed;
    const t = 0.55 + rand() * 0.25;
    const x = vx * t;
    const y = vy * t + 0.5 * 900 * t * t;
    parts.push(
      `tl.set("#${id}s${i}",{x:0,y:0,opacity:1},${fmt(at)});`,
      `tl.to("#${id}s${i}",{x:${fmt(x)},duration:${fmt(t)},ease:"none"},${fmt(at)});`,
      `tl.to("#${id}s${i}",{y:${fmt(y)},opacity:0,duration:${fmt(t)},ease:"power2.in"},${fmt(at)});`,
    );
  }
  return parts.join("");
}

export function sparksHtml({ id, w, h }) {
  return Array.from({ length: 9 }, (_, i) => `<i id="${id}s${i}" class="sp" style="left:${w / 2 - 4}px;top:${h / 2 - 4}px"></i>`).join("");
}

export const SPARKS_CSS = `.sp{position:absolute;width:8px;height:8px;border-radius:50%;background:#DA2E09;opacity:0}`;
