// Vista previa de una plantilla de cortinillas SIN renderizar: un único HTML autocontenido (gsap y fuentes en línea) que
// el componente <hyperframes-player> del navegador reproduce con `srcdoc`. Muestra un clip de relleno, la cortinilla de
// inicio y la final con los mismos tiempos que el render real (mismas capas: `layers/cortinilla` y `layers/outro`).
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { cortinillaLayer } from "./layers/cortinilla.mjs";
import { outroLayer } from "./layers/outro.mjs";

const require = createRequire(import.meta.url);
const pkgDir = (spec) => join(require.resolve(`${spec}/package.json`), "..");
const dataUri = (file) => `data:font/woff2;base64,${readFileSync(file).toString("base64")}`;

export const LEAD = 1.2; // segundos de clip de relleno antes de la cortinilla de inicio
export const TAIL = 1.0; // y entre la cortinilla de inicio y la final

let cache = null;
function assets() {
  cache ??= {
    gsap: readFileSync(join(pkgDir("gsap"), "dist", "gsap.min.js"), "utf8"),
    inter: dataUri(join(pkgDir("@fontsource/inter"), "files", "inter-latin-800-normal.woff2")),
    cormorant: dataUri(join(pkgDir("@fontsource/cormorant"), "files", "cormorant-latin-600-italic.woff2")),
    mono: dataUri(join(pkgDir("@fontsource/jetbrains-mono"), "files", "jetbrains-mono-latin-500-normal.woff2")),
  };
  return cache;
}

/** @param {{cortinilla:{duration:number,color:string,title:string,kicker:string}, outro:{duration:number,color:string,handle:string,text:string,like:string,subscribe:string}}} request */
export function buildPreviewHtml(request) {
  const a = assets();
  const C = request.cortinilla;
  const O = request.outro;
  const outroStart = Number((LEAD + C.duration + TAIL).toFixed(3));
  const total = Number((outroStart + O.duration).toFixed(3));
  const start = cortinillaLayer({ ...C, at: LEAD, fps: 30 });
  const end = outroLayer({ ...O, start: outroStart });
  return `<!doctype html>
<html lang="es"><head><meta charset="UTF-8"/><meta name="viewport" content="width=1080, height=1920"/>
<script>${a.gsap}</script>
<style>
@font-face{font-family:"InterX";font-weight:800;src:url(${a.inter}) format("woff2")}
@font-face{font-family:"CormorantX";font-weight:600;font-style:italic;src:url(${a.cormorant}) format("woff2")}
@font-face{font-family:"JetBrainsX";font-weight:500;src:url(${a.mono}) format("woff2")}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1920px;overflow:hidden;background:#000}
#root{position:relative;width:1080px;height:1920px;overflow:hidden}
.fill{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:linear-gradient(160deg,#2b2f36,#14161a);color:rgba(255,255,255,.28);font-family:InterX,sans-serif;font-weight:800;font-size:72px;letter-spacing:6px}
${start.css}
${end.css}
</style></head>
<body>
<div id="root" data-composition-id="root" data-start="0" data-duration="${total}" data-width="1080" data-height="1920">
  <div id="fillA" class="clip fill" data-start="0" data-duration="${LEAD}" data-track-index="0">TU CLIP</div>
  <div id="fillB" class="clip fill" data-start="${Number((LEAD + C.duration).toFixed(3))}" data-duration="${TAIL}" data-track-index="0">TU CLIP</div>
  ${start.html}
  ${end.html}
</div>
<script>
const tl = gsap.timeline({ paused: true });
${start.script}
${end.script}
tl.set({}, {}, ${total});
window.__timelines = window.__timelines || {};
window.__timelines["root"] = tl;
tl.seek(0);
</script>
</body></html>`;
}

export const previewDuration = (request) => Number((LEAD + request.cortinilla.duration + TAIL + request.outro.duration).toFixed(3));
