// Motivo `emoji`: un emoji de color que entra con pop, da un salto de énfasis en la palabra y sale. Con `target` es una
// pequeña escena: el emoji principal llega a saltos desde la izquierda hasta el objetivo y la llegada cae EN la palabra
// (p. ej. 🐔 → 🗳️ cuando dice «vótame gallina»; el objetivo rebota al recibirlo). Va en una franja de la mitad de abajo,
// por encima de las tarjetas (`keyword`), para que no se pisen. Con imágenes recortadas reales llegará con la librería de
// assets (F7b); mientras, los emojis de color (Noto Color Emoji) hacen de objetos.
import { escapeHtml } from "../html.mjs";

const fmt = (n) => Number(n.toFixed(3));
const SIZE = 150;
const HOPS = 3;
const HOP_HEIGHT = 110;

/** @param {{id:string, item:{emoji:string, target?:string}, t0:number, at:number, t1:number}} p  tiempos de SALIDA */
export function emojiMotif({ id, item, t0, at, t1, zones }) {
  const main = escapeHtml(item.emoji);
  const target = item.target ? escapeHtml(item.target) : null;
  const html = `<div id="${id}" class="gfx em"><span id="${id}m" class="emj">${main}</span>${target ? `<span id="${id}t" class="emj">${target}</span>` : ""}</div>`;
  const css = `.em{left:0;width:1080px;height:200px}
.emj{position:absolute;top:20px;font-size:${SIZE}px;line-height:1;font-family:InterX,sans-serif}  /* el emoji cae a la fuente de color del sistema; nombrarla sin @font-face no pasa el linter */`;
  const cssItem = target
    ? `#${id}m{left:0}#${id}t{left:790px}`
    : `#${id}m{left:${(1080 - SIZE) / 2}px}`;
  const exit = fmt(Math.max(at, t1 - 0.3));
  const parts = [`tl.fromTo("#${id}",{opacity:0},{opacity:1,duration:0.15},${fmt(t0)});`];
  if (!target) {
    parts.push(
      `tl.fromTo("#${id}m",{scale:0.4,y:30},{scale:1,y:0,duration:0.42,ease:"back.out(1.9)"},${fmt(t0)});`,
      `tl.to("#${id}m",{y:-60,duration:0.12,ease:"power2.out",yoyo:true,repeat:1},${fmt(at)});`,
    );
  } else {
    // el emoji mira a la izquierda en casi todos los sets: se voltea para que avance hacia la derecha
    const fromX = -220;
    const toX = 620;
    const start = t0 + 0.05;
    const hop = Math.max(0.18, (at - start) / HOPS);
    parts.push(`tl.set("#${id}m",{x:${fromX},scaleX:-1},${fmt(t0)});`);
    parts.push(`tl.fromTo("#${id}t",{scale:0.4,y:30},{scale:1,y:0,duration:0.4,ease:"back.out(1.9)"},${fmt(t0)});`);
    for (let i = 0; i < HOPS; i++) {
      const hs = start + i * hop;
      const x0 = fromX + ((toX - fromX) * i) / HOPS;
      const x1 = fromX + ((toX - fromX) * (i + 1)) / HOPS;
      parts.push(
        `tl.fromTo("#${id}m",{x:${fmt(x0)}},{x:${fmt(x1)},duration:${fmt(hop)},ease:"none"},${fmt(hs)});`,
        `tl.to("#${id}m",{y:-${HOP_HEIGHT},duration:${fmt(hop / 2)},ease:"power2.out"},${fmt(hs)});`,
        `tl.to("#${id}m",{y:0,duration:${fmt(hop / 2)},ease:"power2.in"},${fmt(hs + hop / 2)});`,
      );
    }
    // llegada (en la palabra): el objetivo rebota y el principal da un saltito de alegría
    parts.push(
      `tl.fromTo("#${id}t",{scale:1},{scale:1.28,duration:0.12,ease:"power2.out",yoyo:true,repeat:1},${fmt(at)});`,
      `tl.to("#${id}m",{y:-70,duration:0.14,ease:"power2.out",yoyo:true,repeat:1},${fmt(at + 0.05)});`,
    );
  }
  parts.push(`tl.to("#${id}",{opacity:0,duration:0.3,ease:"power3.in"},${exit});`, `tl.set("#${id}",{visibility:"hidden"},${fmt(t1)});`);
  return { html, css, cssItem: `#${id}{top:${zones.strip}px}${cssItem}`, script: parts.join("") };
}
