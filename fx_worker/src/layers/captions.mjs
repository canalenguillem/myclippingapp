// Subtítulos karaoke por palabra, en dos estilos según el speaker (§7.2 del md):
//   sans_upper   Inter ExtraBold en MAYÚSCULAS
//   serif_italic Cormorant SemiBold cursiva
// La palabra que suena va en el color de acento con un pequeño «pop»; las que aún no se dicen, atenuadas.
import { escapeHtml } from "../html.mjs";

const BREAK_AFTER = /[.,?!;:…]["'»”’)\]]*$/;
const MAX_WORDS = 4;
const MAX_CHARS = 22;
const MAX_GAP = 0.35;
const MAX_WIDTH = 960;
const ADVANCE = { sans_upper: 0.7, serif_italic: 0.42 }; // ancho medio de un carácter, en «em»

export const styleOf = (word, speakers) => speakers[word.speaker]?.caption_style ?? "sans_upper";

/** Frases cortas: ≤ 4 palabras y ~22 caracteres; corte tras puntuación, tras una pausa y al cambiar de speaker. */
export function groupPhrases(words, duration) {
  const usable = words.filter((w) => w.start < duration);
  const groups = [];
  let cur = [];
  const chars = (g) => g.map((w) => w.text).join(" ").length;
  for (const w of usable) {
    const prev = cur[cur.length - 1];
    if (
      prev &&
      (cur.length >= MAX_WORDS ||
        w.start - prev.end > MAX_GAP ||
        BREAK_AFTER.test(prev.text) ||
        w.speaker !== prev.speaker ||
        chars(cur) + 1 + w.text.length > MAX_CHARS)
    ) {
      groups.push(cur);
      cur = [];
    }
    cur.push(w);
  }
  if (cur.length) groups.push(cur);
  return groups;
}

/** Tamaño que cabe en 960 px: si la frase es larga se reduce (nunca por debajo de 40 px). */
export function fitFontSize(text, style, base) {
  const needed = text.length * ADVANCE[style] * base;
  return needed <= MAX_WIDTH ? base : Math.max(40, Math.floor(MAX_WIDTH / (text.length * ADVANCE[style])));
}

const fmt = (n) => Number(n.toFixed(3));

export function captionsLayer({ words, speakers, duration, preset, center, height }) {
  const groups = groupPhrases(words, duration);
  const inactive = `rgba(${preset.ink === "#1D1A17" ? "29,26,23" : "255,255,255"},${preset.inactiveAlpha})`;
  const html = groups
    .map((g, gi) => {
      const style = styleOf(g[0], speakers);
      const text = g.map((w) => w.text).join(" ");
      const upper = style === "sans_upper" || preset.uppercaseSerif;
      const size = fitFontSize(text, style, style === "sans_upper" ? preset.sansSize : preset.serifSize);
      const spans = g
        .map((w, wi) => `<span class="w" id="w${gi}_${wi}">${escapeHtml(upper ? w.text.toUpperCase() : w.text)}</span>`)
        .join(" ");
      return `<div class="phrase ${style === "sans_upper" ? "sans" : "serif"}" id="p${gi}" style="font-size:${size}px">${spans}</div>`;
    })
    .join("\n");
  const stroke = preset.stroke ? "-webkit-text-stroke:6px #000;paint-order:stroke fill;" : "";
  const shadow = preset.band ? "" : "text-shadow:0 4px 14px rgba(0,0,0,.7);";
  const css = `
#caps{position:absolute;left:0;top:${center - height / 2}px;width:1080px;height:${height}px}
.phrase{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;gap:0.36em;opacity:0;white-space:nowrap;color:${preset.ink};${shadow}${stroke}}
.phrase.sans{font-family:InterX,sans-serif;font-weight:800}
.phrase.serif{font-family:CormorantX,serif;font-style:italic;font-weight:600}
.w{display:inline-block;color:${inactive}}`;
  const script = groups
    .map((g, gi) => {
      const next = groups[gi + 1];
      const last = g[g.length - 1];
      const show = fmt(Math.max(0, g[0].start - 0.04));
      const hideAt = Math.min(duration, last.end + 0.25, next ? Math.max(last.end, next[0].start - 0.04) : Infinity);
      const perWord = g
        .map((w, wi) => {
          const nextStart = g[wi + 1]?.start ?? w.end;
          return (
            `tl.set("#w${gi}_${wi}",{color:"${preset.accent}"},${fmt(w.start)});` +
            (preset.activeScale > 1 ? `tl.fromTo("#w${gi}_${wi}",{scale:${preset.activeScale}},{scale:1,duration:0.15},${fmt(w.start)});` : "") +
            `tl.set("#w${gi}_${wi}",{color:"${preset.ink}"},${fmt(Math.max(w.start, nextStart))});`
          );
        })
        .join("");
      return `tl.fromTo("#p${gi}",{opacity:0,y:6},{opacity:1,y:0,duration:0.14},${show});${perWord}tl.set("#p${gi}",{opacity:0},${fmt(hideAt)});`;
    })
    .join("\n");
  return { html: `<div id="caps">${html}</div>`, css, script };
}
