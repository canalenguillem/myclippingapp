// Gancho: titular de pocas palabras en los primeros segundos. Entra desenfocado y se aclara; en el preset
// editorial la última palabra va en serif cursiva y color de acento (la «palabra clave» del estilo de referencia).
import { escapeHtml } from "../html.mjs";

const fmt = (n) => Number(n.toFixed(3));

export function hookLayer({ hook, preset }) {
  const words = hook.text.trim().split(/\s+/);
  const chars = hook.text.trim().length;
  const size = chars <= 16 ? 92 : chars <= 28 ? 76 : 62;
  const text = preset.band ? words.map((w) => w.toUpperCase()) : words.map((w) => w.toUpperCase());
  const last = text.pop();
  const lead = text.map(escapeHtml).join(" ");
  const accent = preset.band ? `<span class="acc">${escapeHtml(last)}</span>` : escapeHtml(last);
  const html = `<div id="hook">${lead ? lead + " " : ""}${accent}</div>`;
  const css = `
#hook{position:absolute;left:80px;width:920px;top:130px;text-align:center;font-family:InterX,sans-serif;font-weight:800;font-size:${size}px;line-height:1.05;color:${preset.hookColor};text-shadow:0 6px 18px rgba(0,0,0,.65);opacity:0}
#hook .acc{font-family:CormorantX,serif;font-style:italic;font-weight:600;text-transform:none;color:${preset.accent}}`;
  const end = fmt(hook.duration);
  const script =
    `tl.fromTo("#hook",{opacity:0,y:40,filter:"blur(24px)"},{opacity:1,y:0,filter:"blur(0px)",duration:0.5,ease:"power3.out"},0.1);` +
    `tl.to("#hook",{opacity:0,duration:0.3,ease:"power3.in"},${fmt(Math.max(0.7, hook.duration - 0.3))});` +
    `tl.set("#hook",{visibility:"hidden"},${end});`;
  return { html, css, script };
}
