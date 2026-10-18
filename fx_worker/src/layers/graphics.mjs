// Capa de gráficos ligados a la transcripción. Cada gráfico se ancla a un instante `at` del clip (el inicio de la palabra
// gancho); entra `lead` s antes y vive `duration` s en total. Todos los tiempos pasan por el mapa de tiempos único.
import { MOTIFS } from "../motifs/index.mjs";

/** Ventana [start, end] de un gráfico en segundos del CLIP (sin cortinillas), acotada al clip. */
export function graphicWindow(item, clipDuration) {
  const start = Math.max(0, item.at - item.lead);
  return [start, Math.min(clipDuration, start + item.duration)];
}

/**
 * Zonas de los gráficos según el diseño. `split`: tarjeta y franja de emoji en la mitad de abajo. `full`: la parte de
 * abajo es una copia difuminada del vídeo (la hace ffmpeg) y las dos comparten ese hueco bajo la banda de papel. En ambos
 * casos por encima del 15 % inferior que tapa la interfaz de Shorts (y ≥ 1632).
 */
export function graphicZones(layout) {
  if (layout.mode !== "full") return { card: 1290, strip: 1100 };
  const topH = Math.floor((1920 * layout.top_ratio) / 2) * 2;
  return { card: Math.min(topH + 70, 1632 - 230), strip: Math.min(topH + 85, 1632 - 200) };
}

export function graphicsLayer({ items, map, clipDuration, zones = graphicZones({ mode: "split" }) }) {
  const parts = { html: [], css: [], cssItem: [], script: [] };
  const sfx = [];
  items.forEach((item, i) => {
    const [s, e] = graphicWindow(item, clipDuration);
    const id = `g${i}`;
    const out = MOTIFS[item.type]({ id, item, t0: map.out(s), at: map.out(item.at), t1: map.out(e), zones });
    parts.html.push(out.html);
    parts.css.push(out.css);
    if (out.cssItem) parts.cssItem.push(out.cssItem);
    parts.script.push(out.script);
    sfx.push({ id, type: item.type, at: map.out(s) });
  });
  const css = `.gfx{position:absolute;opacity:0}\n${[...new Set(parts.css)].join("\n")}\n${parts.cssItem.join("\n")}`;
  return { html: parts.html.join("\n  "), css: items.length ? css : "", script: parts.script.join("\n"), sfx };
}
