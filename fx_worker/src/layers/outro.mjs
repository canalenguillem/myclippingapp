// Cortinilla final «cta_subscribe»: SIEMPRE va al final del short (el backend siempre la manda). En tiempo de salida
// ocupa [start, start + duration], justo tras el último fotograma del clip. El barrido de entrada (0,42 s) tapa ese
// último fotograma compuesto (con banda y subtítulos) y el color de marca se queda hasta el final: NO vuelve a
// destapar el clip. Sobre el color: llamada a la acción en serif cursiva, handle del canal y los dos botones.
// El builder pone el fotograma congelado bajo el barrido.
import { escapeHtml } from "../html.mjs";
import { SWEEP } from "./cortinilla.mjs";

const BASE = 2.5;
const fmt = (n) => Number(n.toFixed(3));

/** Tamaño de la llamada a la acción según su longitud (en 880 px de ancho caben ≤ 2 líneas). */
export function callSize(text) {
  const n = text.trim().length;
  return n <= 18 ? 110 : n <= 36 ? 84 : 64;
}

/** Tamaño del handle: 72 px como máximo, reducido para que quepa en 920 px. */
export function handleSize(handle) {
  return Math.max(36, Math.min(72, Math.floor(920 / (Math.max(1, handle.length) * 0.62))));
}

export function outroLayer({ start, duration, color, handle = "", text = "", like = "ME GUSTA", subscribe = "SUSCRÍBETE" }) {
  const k = Math.min(1, duration / BASE);
  const at = (x) => fmt(start + x * k);
  const sweepSvg = `<svg id="osweep" class="sweep" width="1560" height="1920" viewBox="0 0 1560 1920">
      <path d="M0 0 H1230 Q1560 960 1230 1920 H0 Z" fill="#fff" transform="translate(46 0)"/>
      <path d="M0 0 H1230 Q1560 960 1230 1920 H0 Z" fill="${color}"/>
    </svg>`;
  const html = `<div id="outro" class="clip" data-start="${fmt(start)}" data-duration="${fmt(duration)}" data-track-index="6">
    ${sweepSvg}
    <div id="octa">
      ${text.trim() ? `<div id="otext">${escapeHtml(text.trim())}</div>` : ""}
      ${handle.trim() ? `<div id="ohandle">${escapeHtml(handle.trim())}</div>` : ""}
      <div id="obtns"><span id="olike" class="obtn">${escapeHtml(like)}</span><span id="osub" class="obtn">${escapeHtml(subscribe)}</span></div>
    </div>
  </div>`;
  const css = `#outro{position:absolute;inset:0}
#octa{position:absolute;left:100px;top:620px;width:880px;height:680px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:34px;text-align:center}
#otext{font-family:CormorantX,serif;font-style:italic;font-weight:600;font-size:${callSize(text)}px;line-height:1.05;color:#fff;opacity:0}
#ohandle{font-family:InterX,sans-serif;font-weight:800;font-size:${handleSize(handle.trim())}px;color:#fff;opacity:0;white-space:nowrap}
#obtns{display:flex;gap:26px;margin-top:20px}
.obtn{display:inline-block;padding:24px 50px;border-radius:60px;background:#F3EEE2;color:#1D1A17;font-family:InterX,sans-serif;font-weight:800;font-size:46px;opacity:0;white-space:nowrap}`;
  const blur = (sel, x) => `tl.fromTo("${sel}",{opacity:0,y:24,filter:"blur(14px)"},{opacity:1,y:0,filter:"blur(0px)",duration:${fmt(0.45 * k)},ease:"power3.out"},${at(x)});`;
  const pop = (sel, x) => `tl.fromTo("${sel}",{opacity:0,scale:0.6},{opacity:1,scale:1,duration:${fmt(0.4 * k)},ease:"back.out(1.8)"},${at(x)});`;
  const script = [
    `tl.fromTo("#osweep",{x:-1560},{x:0,duration:${SWEEP},ease:"power2.inOut"},${fmt(start)});`,
    text.trim() ? blur("#otext", 0.55) : "",
    handle.trim() ? blur("#ohandle", 0.8) : "",
    pop("#olike", 1.0),
    pop("#osub", 1.15),
  ].filter(Boolean).join("\n");
  return { html, css, script };
}
