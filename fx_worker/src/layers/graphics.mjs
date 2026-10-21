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
export function graphicZones(layout, bandBottom = 0) {
  const base = layout.mode !== "full"
    ? { card: 1290, strip: 1100 }
    : (() => {
        const topH = Math.floor((1920 * layout.top_ratio) / 2) * 2;
        return { card: Math.min(topH + 70, 1632 - 230), strip: Math.min(topH + 85, 1632 - 200) };
      })();
  // Si la banda de papel (subtítulos) está más abajo que el corte, los gráficos van debajo de ella y no sobre los subtítulos.
  return { card: Math.min(Math.max(base.card, bandBottom + 12), 1632 - 230), strip: Math.min(Math.max(base.strip, bandBottom + 12), 1632 - 200) };
}

export function graphicsLayer({ items, map, clipDuration, zones = graphicZones({ mode: "split" }), files = {}, accent = "#DA2E09" }) {
  const parts = { html: [], css: [], cssItem: [], script: [] };
  const sfx = [];
  items.forEach((item, i) => {
    const [s, e] = graphicWindow(item, clipDuration);
    const id = `g${i}`;
    const out = MOTIFS[item.type]({ id, item, t0: map.out(s), at: map.out(item.at), t1: map.out(e), zones, files, accent });
    parts.html.push(out.html);
    parts.css.push(out.css);
    if (out.cssItem) parts.cssItem.push(out.cssItem);
    parts.script.push(out.script);
    // sin sonidos repetidos: golpear y explotar en la misma palabra suena UN golpe, no dos encima
    const own = (out.sfx ?? [{ kind: "pop", at: map.out(s) }]).filter((fx, n, all) => all.findIndex((o) => o.kind === fx.kind && Math.abs(o.at - fx.at) < 0.01) === n);
    own.forEach((fx, n) => sfx.push({ id: n === 0 ? `sfx${id}` : `sfx${id}_${n}`, kind: fx.kind, at: fx.at }));
  });
  const css = `.gfx{position:absolute;opacity:0}\n${[...new Set(parts.css)].join("\n")}\n${parts.cssItem.join("\n")}`;
  return { html: parts.html.join("\n  "), css: items.length ? css : "", script: parts.script.join("\n"), sfx };
}
