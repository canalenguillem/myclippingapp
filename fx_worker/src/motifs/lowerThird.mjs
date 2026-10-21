// Motivo `lower_third`: rótulo de nombre y cargo (§8 del md): panel de papel que entra desde la izquierda con una barra roja
// que crece; el nombre en Inter 800 y el cargo en mono. Sale con ease_in.
import { escapeHtml } from "../html.mjs";

const fmt = (n) => Number(n.toFixed(3));
const W = 760;
const H = 150;

export function lowerThirdMotif({ id, item, t0, at, t1, zones, accent = "#DA2E09" }) {
  const name = item.name.trim();
  const role = (item.role ?? "").trim();
  const nameSize = Math.min(58, Math.floor(640 / (name.length * 0.62)));
  const html = `<div id="${id}" class="gfx lt"><b id="${id}b"></b><div><strong style="font-size:${nameSize}px">${escapeHtml(name)}</strong>${role ? `<em>${escapeHtml(role.toUpperCase())}</em>` : ""}</div></div>`;
  const css = `.lt{left:60px;width:${W}px;height:${H}px;background:#F3EEE2;box-shadow:0 12px 14px rgba(0,0,0,.4);border-radius:14px;display:flex;align-items:center;overflow:hidden}
.lt b{width:14px;align-self:stretch;background:${accent};transform-origin:50% 0;flex:0 0 14px}
.lt div{display:flex;flex-direction:column;gap:6px;padding:0 26px}
.lt strong{font-family:InterX,sans-serif;font-weight:800;color:#1D1A17;white-space:nowrap}
.lt em{font-style:normal;font-family:JetBrainsX,monospace;font-weight:500;font-size:26px;letter-spacing:3px;color:${accent};white-space:nowrap}`;
  const exit = fmt(Math.max(at, t1 - 0.3));
  const script =
    `tl.fromTo("#${id}",{opacity:0,x:-120},{opacity:1,x:0,duration:0.4,ease:"back.out(1.5)"},${fmt(t0)});` +
    `tl.fromTo("#${id}b",{scaleY:0},{scaleY:1,duration:0.3,ease:"power3.out"},${fmt(t0 + 0.1)});` +
    `tl.to("#${id}",{opacity:0,x:-80,duration:0.3,ease:"power3.in"},${exit});` +
    `tl.set("#${id}",{visibility:"hidden"},${fmt(t1)});`;
  return { sfx: [{ kind: "whoosh", at: t0 }], html, css, cssItem: `#${id}{top:${zones.card + 40}px}`, script };
}
