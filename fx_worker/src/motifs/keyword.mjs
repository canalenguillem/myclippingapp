// Motivo `keyword`: tarjeta de papel con la palabra clave (§8 del md). Entra con pop (back_out) 0,3–0,8 s antes de la
// palabra, da un pequeño golpe de énfasis en ella y sale con ease_in. Barra roja a la izquierda, texto en Inter 800.
import { escapeHtml } from "../html.mjs";

const fmt = (n) => Number(n.toFixed(3));
const CARD_W = 500;
const CARD_H = 230;
// Los gráficos van en la mitad de ABAJO (la escena completa), dejando libre la cara del plano corto, y por encima del 15 %
// inferior que tapa la interfaz de Shorts (y ≥ 1632 px). `top` solo para clips donde la cara no está arriba.
export const TOP_ZONE = 600; // `zone: "top"`; la zona de abajo la fija el diseño (`graphicZones`)

/** Tamaño del texto: 68 px que se reducen para que quepa en el ancho útil de la tarjeta (≥ 40 px). */
export function keywordSize(text) {
  const need = text.length * 0.66 * 68;
  return need <= 410 ? 68 : Math.max(40, Math.floor(410 / (text.length * 0.66)));
}

/** @param {{id:string, item:{text:string}, t0:number, at:number, t1:number}} p  tiempos de SALIDA (ya con el mapa de tiempos) */
export function keywordMotif({ id, item, t0, at, t1, zones }) {
  const top = item.zone === "top" ? TOP_ZONE : zones.card;
  const text = item.text.trim().toUpperCase();
  const html = `<div id="${id}" class="gfx kw"><b></b><span style="font-size:${keywordSize(text)}px">${escapeHtml(text)}</span></div>`;
  const css = `.kw{left:${(1080 - CARD_W) / 2}px;width:${CARD_W}px;height:${CARD_H}px;border-radius:26px;background:#F3EEE2;box-shadow:0 12px 14px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;overflow:hidden}
.kw b{position:absolute;left:0;top:0;bottom:0;width:18px;background:#DA2E09}
.kw span{font-family:InterX,sans-serif;font-weight:800;color:#1D1A17;white-space:nowrap;padding-left:18px}`;
  const exit = fmt(Math.max(at, t1 - 0.3));
  const script =
    `tl.fromTo("#${id}",{opacity:0,scale:0.55,y:40},{opacity:1,scale:1,y:0,duration:0.42,ease:"back.out(1.7)"},${fmt(t0)});` +
    `tl.fromTo("#${id}",{scale:1},{scale:1.06,duration:0.1,yoyo:true,repeat:1,ease:"power2.out"},${fmt(at)});` +
    `tl.to("#${id}",{opacity:0,scale:0.7,duration:0.3,ease:"power3.in"},${exit});` +
    `tl.set("#${id}",{visibility:"hidden"},${fmt(t1)});`;
  return { html, css, cssItem: `#${id}{top:${top}px}`, script };
}
