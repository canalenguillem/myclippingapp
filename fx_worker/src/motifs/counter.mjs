// Motivo `counter`: tarjeta de papel con una cifra que rueda de `from_value` a `to_value` y se para EN la palabra (§8 del md).
// La cifra se precalcula en pasos (un <span> por paso, visibles uno a uno): no depende de callbacks de GSAP, que no se
// ejecutan al buscar un fotograma, y es determinista.
import { escapeHtml } from "../html.mjs";

const fmt = (n) => Number(n.toFixed(3));
const CARD_W = 560;
const CARD_H = 250;
const STEP = 0.05;          // s entre cifras del rodillo
const ROLL_MAX = 1.1;       // s que dura el rodillo como máximo

const decimalsOf = (n) => Math.min(2, (String(n).split(".")[1] ?? "").length);

/** Número en español: «.» de millares desde 1000 y «,» decimal. */
export function formatNumber(value, decimals) {
  const [int, dec] = Math.abs(value).toFixed(decimals).split(".");
  const grouped = Number(int) >= 1000 ? int.replace(/\B(?=(\d{3})+(?!\d))/g, ".") : int;
  return `${value < 0 ? "-" : ""}${grouped}${dec ? "," + dec : ""}`;
}

/** Cifras del rodillo: de `from` a `to` con ease_out_cubic; la última es siempre exactamente `to`. */
export function rollValues(from, to, steps, decimals) {
  return Array.from({ length: steps + 1 }, (_, k) => {
    const u = k / steps;
    const v = k === steps ? to : from + (to - from) * (1 - (1 - u) ** 3);
    return formatNumber(v, decimals);
  });
}

export function counterMotif({ id, item, t0, at, t1, zones }) {
  const decimals = Math.max(decimalsOf(item.from_value), decimalsOf(item.to_value));
  const rollStart = t0 + 0.3;                                      // tras la entrada de la tarjeta
  const rollEnd = Math.max(rollStart + 0.4, at);                   // y se para en la palabra
  const steps = Math.max(8, Math.round(Math.min(ROLL_MAX, rollEnd - rollStart) / STEP));
  const stepLen = (rollEnd - rollStart) / steps;
  const texts = rollValues(item.from_value, item.to_value, steps, decimals).map((t) => `${item.prefix}${t}${item.suffix}`);
  const longest = Math.max(...texts.map((t) => t.length));
  const size = Math.min(110, Math.floor(480 / (longest * 0.62)));
  const spans = texts.map((t, k) => `<span id="${id}n${k}" class="cn" style="font-size:${size}px">${escapeHtml(t)}</span>`).join("");
  const label = item.label ? `<i>${escapeHtml(item.label.toUpperCase())}</i>` : "";
  const html = `<div id="${id}" class="gfx ct"><b></b><div class="cw">${spans}</div>${label}</div>`;
  const css = `.ct{left:${(1080 - CARD_W) / 2}px;width:${CARD_W}px;height:${CARD_H}px;border-radius:26px;background:#F3EEE2;box-shadow:0 12px 14px rgba(0,0,0,.4);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;overflow:hidden}
.ct b{position:absolute;left:0;top:0;bottom:0;width:18px;background:#DA2E09}
.ct .cw{display:grid;padding-left:18px}
.ct .cn{grid-area:1/1;visibility:hidden;font-family:InterX,sans-serif;font-weight:800;color:#DA2E09;white-space:nowrap;text-align:center;font-variant-numeric:tabular-nums}
.ct i{font-style:normal;font-family:JetBrainsX,monospace;font-weight:500;font-size:26px;letter-spacing:3px;color:#1D1A17;padding-left:18px;white-space:nowrap}`;
  const exit = fmt(Math.max(rollEnd, t1 - 0.3));
  const parts = [
    `tl.fromTo("#${id}",{opacity:0,scale:0.55,y:40},{opacity:1,scale:1,y:0,duration:0.42,ease:"back.out(1.7)"},${fmt(t0)});`,
    `tl.set("#${id}n0",{visibility:"visible"},${fmt(t0)});`,
  ];
  for (let k = 1; k <= steps; k++) {
    const when = fmt(rollStart + k * stepLen);
    parts.push(`tl.set("#${id}n${k - 1}",{visibility:"hidden"},${when});`, `tl.set("#${id}n${k}",{visibility:"visible"},${when});`);
  }
  parts.push(
    `tl.fromTo("#${id}",{scale:1},{scale:1.07,duration:0.1,yoyo:true,repeat:1,ease:"power2.out"},${fmt(rollEnd)});`,
    `tl.to("#${id}",{opacity:0,scale:0.7,duration:0.3,ease:"power3.in"},${exit});`,
    `tl.set("#${id}",{visibility:"hidden"},${fmt(t1)});`,
  );
  return { sfx: [{ kind: "pop", at: t0 }], html, css, cssItem: `#${id}{top:${zones.card}px}`, script: parts.join("") };
}
