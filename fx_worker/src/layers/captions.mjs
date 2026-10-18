// Subtítulos karaoke por palabra. En el paso 4 de F5 hay un solo estilo (blanco con sombra); el paso 5 añade la
// banda de papel, el estilo serif cursiva y el blanco y negro del clip citado.
import { escapeHtml } from "../html.mjs";

const SENTENCE_END = /[.!?…]["'»”’)\]]*$/;
const MAX_WORDS = 3;
const MAX_GAP = 0.5;

/** Agrupa palabras en frases cortas: máximo 3, y corte tras puntuación final o una pausa larga. */
export function groupPhrases(words, duration) {
  const usable = words.filter((w) => w.start < duration);
  const groups = [];
  let cur = [];
  for (const w of usable) {
    const prev = cur[cur.length - 1];
    if (prev && (cur.length >= MAX_WORDS || w.start - prev.end > MAX_GAP || SENTENCE_END.test(prev.text))) {
      groups.push(cur);
      cur = [];
    }
    cur.push(w);
  }
  if (cur.length) groups.push(cur);
  return groups;
}

export function captionsLayer({ words, duration, layout }) {
  const groups = groupPhrases(words, duration);
  const topH = Math.floor((1920 * layout.top_ratio) / 2) * 2;
  const html = groups
    .map(
      (g, gi) =>
        `<div class="phrase" id="p${gi}">${g.map((w, wi) => `<span class="w" id="w${gi}_${wi}">${escapeHtml(w.text.toUpperCase())}</span>`).join(" ")}</div>`,
    )
    .join("\n");
  const css = `
#caps{position:absolute;left:0;top:${topH - 55}px;width:1080px;height:110px}
.phrase{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;gap:18px;opacity:0;font-family:InterX,sans-serif;font-weight:800;font-size:64px;color:#fff;text-shadow:0 4px 14px rgba(0,0,0,.7)}
.w{display:inline-block}`;
  const fmt = (n) => Number(n.toFixed(3));
  const script = groups
    .map((g, gi) => {
      const next = groups[gi + 1];
      const show = fmt(Math.max(0, g[0].start - 0.04));
      const hideAt = Math.min(duration, g[g.length - 1].end + 0.25, next ? Math.max(g[g.length - 1].end, next[0].start - 0.04) : Infinity);
      const words = g
        .map((w, wi) => `tl.set("#w${gi}_${wi}",{color:"#DA2E09"},${fmt(w.start)});tl.fromTo("#w${gi}_${wi}",{scale:1.05},{scale:1,duration:0.15},${fmt(w.start)});`)
        .join("");
      return `tl.fromTo("#p${gi}",{opacity:0,y:6},{opacity:1,y:0,duration:0.14},${show});${words}tl.set("#p${gi}",{opacity:0},${fmt(hideAt)});`;
    })
    .join("\n");
  return { html: `<div id="caps">${html}</div>`, css, script };
}
