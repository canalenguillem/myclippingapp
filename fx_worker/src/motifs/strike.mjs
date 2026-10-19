// Motivo `strike`: tarjeta con la palabra y un aspa a rotulador rojo (dos trazos de 0,22 s) que la tacha EN la palabra (§8 del md).
import { escapeHtml } from "../html.mjs";
import { keywordSize } from "./keyword.mjs";

const fmt = (n) => Number(n.toFixed(3));
const CARD_W = 500;
const CARD_H = 230;
const STROKE = 0.22;

export function strikeMotif({ id, item, t0, at, t1, zones }) {
  const text = item.text.trim().toUpperCase();
  const cross = (d, n) => `<path id="${id}s${n}" d="${d}" pathLength="1"/>`;
  const html = `<div id="${id}" class="gfx sk"><b></b><span id="${id}w" style="font-size:${keywordSize(text)}px">${escapeHtml(text)}</span>` +
    `<svg viewBox="0 0 ${CARD_W} ${CARD_H}" width="${CARD_W}" height="${CARD_H}">${cross("M 60 50 L 440 185", 1)}${cross("M 445 48 L 55 188", 2)}</svg></div>`;
  const css = `.sk{left:${(1080 - CARD_W) / 2}px;width:${CARD_W}px;height:${CARD_H}px;border-radius:26px;background:#F3EEE2;box-shadow:0 12px 14px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;overflow:hidden}
.sk b{position:absolute;left:0;top:0;bottom:0;width:18px;background:#1D1A17}
.sk span{font-family:InterX,sans-serif;font-weight:800;color:#1D1A17;white-space:nowrap;padding-left:18px}
.sk svg{position:absolute;left:0;top:0}
.sk path{fill:none;stroke:#DA2E09;stroke-width:16;stroke-linecap:round;stroke-dasharray:1;stroke-dashoffset:1}`;
  const exit = fmt(Math.max(at + 2 * STROKE + 0.3, t1 - 0.3));
  const script =
    `tl.fromTo("#${id}",{opacity:0,scale:0.55,y:40},{opacity:1,scale:1,y:0,duration:0.42,ease:"back.out(1.7)"},${fmt(t0)});` +
    `tl.fromTo("#${id}s1",{strokeDashoffset:1},{strokeDashoffset:0,duration:${STROKE},ease:"power2.out"},${fmt(at)});` +
    `tl.fromTo("#${id}s2",{strokeDashoffset:1},{strokeDashoffset:0,duration:${STROKE},ease:"power2.out"},${fmt(at + STROKE)});` +
    `tl.to("#${id}w",{opacity:0.45,duration:0.2,ease:"power2.out"},${fmt(at + STROKE)});` +
    `tl.to("#${id}",{opacity:0,scale:0.7,duration:0.3,ease:"power3.in"},${exit});` +
    `tl.set("#${id}",{visibility:"hidden"},${fmt(t1)});`;
  return { sfx: [{ kind: "pop", at: t0 }, { kind: "whoosh", at }], html, css, cssItem: `#${id}{top:${zones.card}px}`, script };
}
