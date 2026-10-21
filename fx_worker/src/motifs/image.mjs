// Motivo `image`: una imagen de la librería del usuario (una hucha, un logo…), con un estilo y un efecto.
//   style  original | card (tarjeta de papel inclinada −5°, §8 del md) | silhouette (tinta) | red (rojo de marca)
//   effect pop (entra con rebote y sale con ease_in) | vaporize (se descompone en polvo en la palabra) | break (se parte en dos)
// Entra 0,3–0,8 s antes de la palabra; la acción fuerte (el golpe, la vaporización, la rotura) cae EN la palabra.
import { breakHtml, breakScript, explodeScript, RING_CSS, ringHtml, sparksCss, sparksHtml, TILES_CSS, tilesHtml, vaporizeScript } from "./dissolve.mjs";
import { entryScript, shakeScript } from "./entry.mjs";

const fmt = (n) => Number(n.toFixed(3));
// Tamaños pensados para caber bajo la banda de papel también en pantalla completa (zona de gráficos y ≥ 1318, h ≤ 314).
const BOX = 270;                       // imagen en un cuadrado (se ajusta con contain)
export const CARD = { w: 270, h: 310, inset: 34 };
const GRID = 10;

export function imageBox(style) {
  return style === "card" ? { w: CARD.w, h: CARD.h } : { w: BOX, h: BOX };
}

/** HTML del contenido (w × h) según el estilo. `src` es el fichero ya copiado al proyecto de render. */
export function imageInner(style, src, { w, h }, accent = "#DA2E09") {
  if (style === "silhouette" || style === "red") {
    const color = style === "red" ? accent : "#1D1A17";
    return `<div class="imk" style="width:${w}px;height:${h}px;background:${color};-webkit-mask:url(${src}) center/contain no-repeat;mask:url(${src}) center/contain no-repeat"></div>`;
  }
  if (style === "card") {
    const s = w - 2 * CARD.inset;
    return `<div class="imc" style="width:${w}px;height:${h}px"><img src="${src}" alt="" style="left:${CARD.inset}px;top:${CARD.inset}px;width:${s}px;height:${s}px"/></div>`;
  }
  return `<img class="imo" src="${src}" alt="" style="width:${w}px;height:${h}px"/>`;
}

/** @param {{id:string, item:{image:string, style:string, effect:string}, t0:number, at:number, t1:number, zones:{card:number}, files:Record<string,string>}} p */
export function imageMotif({ id, item, t0, at, t1, zones, files, accent = "#DA2E09" }) {
  const style = item.style ?? "original";
  const effect = item.effect ?? "pop";
  const entry = item.entry ?? "pop";
  const box = imageBox(style);
  const src = files[item.image];
  const inner = imageInner(style, src, box, accent);
  const top = Math.min(zones.card, 1632 - box.h);
  const left = (1080 - box.w) / 2;
  const tilt = style === "card" ? -5 : 0;
  let body;
  if (effect === "vaporize") body = tilesHtml({ id, inner, w: box.w, h: box.h, cols: GRID, rows: GRID });
  else if (effect === "explode") body = tilesHtml({ id, inner, w: box.w, h: box.h, cols: GRID, rows: GRID }) + ringHtml({ id, w: box.w, h: box.h });
  else if (effect === "break") body = breakHtml({ id, inner, w: box.w, h: box.h }) + sparksHtml({ id, w: box.w, h: box.h });
  else body = inner;
  const html = `<div id="${id}" class="gfx im">${body}</div>`;
  const css = `.im{overflow:visible}
.imo{display:block;object-fit:contain;filter:drop-shadow(0 10px 12px rgba(0,0,0,.4))}
.imc{position:relative;border-radius:22px;background:#F3EEE2;box-shadow:0 12px 14px rgba(0,0,0,.4)}
.imc img{position:absolute;object-fit:contain}
.imk{display:block}
${TILES_CSS}
${sparksCss(accent)}
${RING_CSS}`;
  const exit = fmt(Math.max(at, t1 - 0.3));
  const seed = Number(id.replace(/\D/g, "")) || 1;
  const enter = entryScript({ id, entry, t0, at, box, left, top, tilt });
  const parts = [enter.script];
  const sfx = [...enter.sfx];
  if (effect === "vaporize") { parts.push(vaporizeScript({ id, cols: GRID, rows: GRID, at, seed })); sfx.push({ kind: "dust", at }); }
  else if (effect === "explode") {
    parts.push(explodeScript({ id, cols: GRID, rows: GRID, w: box.w, h: box.h, at, seed }), shakeScript({ at, amp: 22, seed: seed + 50 }));
    sfx.push({ kind: "thud", at }, { kind: "crack", at });
  } else if (effect === "break") { parts.push(breakScript({ id, w: box.w, h: box.h, at, seed })); sfx.push({ kind: "crack", at }); }
  else if (entry === "pop") parts.push(`tl.fromTo("#${id}",{scale:1},{scale:1.06,duration:0.1,yoyo:true,repeat:1,ease:"power2.out"},${fmt(at)});`);
  if (effect === "pop") parts.push(`tl.to("#${id}",{opacity:0,scale:0.7,duration:0.3,ease:"power3.in"},${exit});`);
  else parts.push(`tl.to("#${id}",{opacity:0,duration:0.25,ease:"power1.in"},${fmt(Math.max(at + 1.6, exit))});`);
  parts.push(`tl.set("#${id}",{visibility:"hidden"},${fmt(t1)});`);
  return { html, css, cssItem: `#${id}{left:${left}px;top:${top}px;width:${box.w}px;height:${box.h}px}`, script: parts.join(""), sfx };
}
