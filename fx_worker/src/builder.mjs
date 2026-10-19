// Genera el proyecto HyperFrames de un render: index.html + medios, en un directorio de trabajo propio.
import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, symlinkSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { extname, join } from "node:path";
import { bandLayer, ROOM } from "./layers/band.mjs";
import { captionsLayer } from "./layers/captions.mjs";
import { cortinillaLayer, SWEEP } from "./layers/cortinilla.mjs";
import { graphicsLayer, graphicZones } from "./layers/graphics.mjs";
import { hookLayer } from "./layers/hook.mjs";
import { outroLayer } from "./layers/outro.mjs";
import { sourceIntervals, treatmentLayer } from "./layers/treatment.mjs";
import { getPreset } from "./presets.mjs";
import { crackWav, dustWav, popWav, shimmerWav, thudWav, whooshWav } from "./sfx.mjs";
import { makeTimeMap, mapIntervals } from "./timemap.mjs";

const require = createRequire(import.meta.url);

const assetPath = (spec) => require.resolve(spec);

/**
 * Un fotograma del clip vertical en `at` segundos, como PNG (el que se ve bajo los barridos de la cortinilla). Si `at`
 * cae pasado el final real del vídeo (el clip dura unas milésimas menos de lo pedido), ffmpeg termina sin error y SIN
 * fichero: se comprueba y se prueba con instantes cada vez más atrás, y al final con el último fotograma (`-sseof`).
 */
function extractFrame(video, at, out) {
  const run = (args) => spawnSync("ffmpeg", ["-v", "error", "-y", ...args, "-i", video, "-frames:v", "1", out]);
  let r;
  for (const back of [0, 0.1, 0.25, 0.5]) {
    r = run(["-ss", String(Math.max(0, at - back))]);
    if (r.status === 0 && existsSync(out)) return;
  }
  r = run(["-sseof", "-0.2"]);
  if (r.status !== 0 || !existsSync(out)) throw new Error(`ffmpeg no pudo extraer un fotograma en ${at} s: ${r.stderr}`);
}

/** `video` es la ruta ABSOLUTA ya resuelta (y comprobada) del clip vertical. */
export function buildProject({ request, video, workDir, orbit = null, images = {} }) {
  mkdirSync(join(workDir, "fonts"), { recursive: true });
  try {
    symlinkSync(video, join(workDir, "clip.mp4")); // sin copiar decenas de MB por render
  } catch {
    copyFileSync(video, join(workDir, "clip.mp4"));
  }
  copyFileSync(join(assetPath("gsap/package.json"), "..", "dist", "gsap.min.js"), join(workDir, "gsap.min.js"));
  const fontsDir = join(assetPath("@fontsource/inter/package.json"), "..", "files");
  copyFileSync(join(fontsDir, "inter-latin-800-normal.woff2"), join(workDir, "fonts", "inter-800.woff2"));
  const serifDir = join(assetPath("@fontsource/cormorant/package.json"), "..", "files");
  copyFileSync(join(serifDir, "cormorant-latin-600-italic.woff2"), join(workDir, "fonts", "cormorant-600i.woff2"));
  const monoDir = join(assetPath("@fontsource/jetbrains-mono/package.json"), "..", "files");
  copyFileSync(join(monoDir, "jetbrains-mono-latin-500-normal.woff2"), join(workDir, "fonts", "jetbrains-500.woff2"));

  const { duration, layout, speakers } = request;
  const preset = getPreset(request.preset);
  const C = request.cortinilla;
  const map = makeTimeMap(C);
  const O = request.outro;
  const clipEnd = map.total(duration); // donde acaba el clip en el vídeo final; ahí empieza la cortinilla final
  const total = Number((clipEnd + (O?.duration ?? 0)).toFixed(3));
  // Todo lo posterior a la cortinilla se desplaza con el mapa de tiempos; las palabras no la cruzan (lo valida el contrato).
  const words = request.words.map((w) => ({ ...w, start: map.out(w.start), end: map.out(w.end) }));
  const sourceSpans = mapIntervals(sourceIntervals(request.words, speakers, duration), map);

  // Zona que la banda debe cubrir: la que pide el backend (subtítulos quemados, con 10 px de margen) o, si no, una
  // franja centrada en el corte entre el plano corto y la escena completa.
  const topH = Math.floor((1920 * layout.top_ratio) / 2) * 2;
  const clampRow = (v) => Math.min(1920 - ROOM, Math.max(ROOM, v));
  const core = request.band
    ? { y0: clampRow(request.band.y0 - 10), y1: clampRow(request.band.y1 + 10) }
    : { y0: clampRow(topH - 45), y1: clampRow(topH + 45) };
  const band = preset.band ? bandLayer({ core, paper: preset.paper }) : null;
  const center = (core.y0 + core.y1) / 2;
  const captions = captionsLayer({ words, speakers, duration: total, preset, center, height: Math.max(90, core.y1 - core.y0), stops: C ? [C.at] : [] });
  const hook = request.hook ? hookLayer({ hook: request.hook, preset }) : null;
  // Imágenes de los gráficos: se copian al proyecto de render con un nombre propio (ruta relativa de la petición → fichero local).
  const gfxFiles = {};
  Object.entries(images).forEach(([rel, abs], n) => {
    const name = `gfx_img${n}${extname(abs).toLowerCase() || ".png"}`;
    copyFileSync(abs, join(workDir, name));
    gfxFiles[rel] = name;
  });
  const graphics = graphicsLayer({ items: request.graphics, map, clipDuration: duration, zones: graphicZones(layout, preset.band ? core.y1 + ROOM : 0), files: gfxFiles });
  const treatment = treatmentLayer({ intervals: sourceSpans });
  let orbitFile = null;
  if (C && orbit) {
    orbitFile = `orbit${extname(orbit).toLowerCase()}`;
    copyFileSync(orbit, join(workDir, orbitFile));
  }
  const cortinilla = C ? cortinillaLayer({ ...C, orbit: orbitFile, fps: request.fps }) : null;
  const outro = O ? outroLayer({ ...O, start: clipEnd }) : null;

  // Sin cortinilla, un solo vídeo. Con ella, dos tramos del mismo fichero y dos fotogramas congelados que se ven bajo
  // los barridos: el último del tramo 1 al entrar y el primero del tramo 2 al salir.
  if (O) extractFrame(join(workDir, "clip.mp4"), duration - 1 / request.fps, join(workDir, "freezeEnd.png"));
  const endImg = O ? `\n    <img id="freezeEnd" class="clip vid" src="freezeEnd.png" data-start="${clipEnd}" data-duration="${SWEEP}" data-track-index="0"/>` : "";
  // Efectos: whoosh en cada barrido (sube al entrar y baja al salir) y brillo mientras se dibuja la píldora. Van muy por
  // debajo de la voz (0,30 y 0,08 de volumen), y los cortes caen en silencios, así que no se pisa ninguna palabra.
  const sfx = [];
  if (request.sfx && (C || O || graphics.sfx.length)) {
    mkdirSync(join(workDir, "sfx"), { recursive: true });
    const put = (name, buf) => writeFileSync(join(workDir, "sfx", name), buf);
    const track = (id, file, start, seconds, volume) =>
      sfx.push(`<audio id="${id}" src="sfx/${file}" data-start="${Number(start.toFixed(3))}" data-duration="${seconds}" data-volume="${volume}"></audio>`);
    if (graphics.sfx.length) {
      const kinds = { pop: { wav: popWav, seconds: 0.12, volume: 0.3 }, dust: { wav: dustWav, seconds: 0.8, volume: 0.14 }, crack: { wav: crackWav, seconds: 0.3, volume: 0.25 },
        thud: { wav: thudWav, seconds: 0.25, volume: 0.45 }, whoosh: { wav: () => whooshWav({ seconds: 0.35, rising: true, seed: 41 }), seconds: 0.35, volume: 0.25 } };
      for (const kind of new Set(graphics.sfx.map((g) => g.kind))) put(`${kind}.wav`, kinds[kind].wav());
      for (const g of graphics.sfx) track(g.id, `${g.kind}.wav`, g.at, kinds[g.kind].seconds, kinds[g.kind].volume);
    }
    if (C) {
      const k = Math.min(1, C.duration / 3.6);
      put("whoosh_up.wav", whooshWav({ seconds: SWEEP, rising: true, seed: 11 }));
      put("whoosh_down.wav", whooshWav({ seconds: SWEEP, rising: false, seed: 12 }));
      put("shimmer.wav", shimmerWav({ seconds: Number((0.95 * k).toFixed(3)), seed: 7 }));
      track("sfxIn", "whoosh_up.wav", C.at, SWEEP, 0.3);
      track("sfxShimmer", "shimmer.wav", C.at + 0.55 * k, Number((0.95 * k).toFixed(3)), 0.08);
      track("sfxOut", "whoosh_down.wav", C.at + C.duration - SWEEP, SWEEP, 0.3);
    }
    if (O) {
      put("whoosh_end.wav", whooshWav({ seconds: SWEEP, rising: true, seed: 13 }));
      track("sfxEnd", "whoosh_end.wav", clipEnd, SWEEP, 0.3);
    }
  }
  let media;
  if (C) {
    const fps = request.fps;
    extractFrame(join(workDir, "clip.mp4"), C.at - 1 / fps, join(workDir, "freezeA.png"));
    extractFrame(join(workDir, "clip.mp4"), C.at, join(workDir, "freezeB.png"));
    const resume = map.out(C.at);
    media = `<video id="clipA" class="clip vid" src="clip.mp4" data-start="0" data-duration="${C.at}" data-media-start="0" data-track-index="0" data-has-audio="true" playsinline></video>
    <img id="freezeA" class="clip vid" src="freezeA.png" data-start="${C.at}" data-duration="${SWEEP}" data-track-index="0"/>
    <img id="freezeB" class="clip vid" src="freezeB.png" data-start="${Number((resume - SWEEP).toFixed(3))}" data-duration="${SWEEP}" data-track-index="0"/>
    <video id="clipB" class="clip vid" src="clip.mp4" data-start="${resume}" data-duration="${Number((duration - C.at).toFixed(3))}" data-media-start="${C.at}" data-track-index="0" data-has-audio="true" playsinline></video>${endImg}`;
  } else {
    media = `<video id="clip" class="clip vid" src="clip.mp4" data-start="0" data-duration="${clipEnd}" data-media-start="0" data-track-index="0" data-has-audio="true" playsinline></video>${endImg}`;
  }

  const html = `<!doctype html>
<html lang="es"><head><meta charset="UTF-8"/><meta name="viewport" content="width=1080, height=1920"/>
<script src="gsap.min.js"></script>
<style>
@font-face{font-family:"InterX";font-weight:800;src:url(fonts/inter-800.woff2) format("woff2")}
@font-face{font-family:"CormorantX";font-weight:600;font-style:italic;src:url(fonts/cormorant-600i.woff2) format("woff2")}
@font-face{font-family:"JetBrainsX";font-weight:500;src:url(fonts/jetbrains-500.woff2) format("woff2")}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1920px;overflow:hidden;background:#000}
#root{position:relative;width:1080px;height:1920px;overflow:hidden}
#vwrap{position:absolute;inset:0}
.vid{position:absolute;inset:0;width:1080px;height:1920px;object-fit:cover}
${band?.css ?? ""}
${captions.css}
${hook?.css ?? ""}
${graphics.css}
${cortinilla?.css ?? ""}
${outro?.css ?? ""}
</style></head>
<body>
<div id="root" data-composition-id="root" data-start="0" data-duration="${total}" data-width="1080" data-height="1920">
  <div id="vwrap">${media}</div>
  ${band?.html ?? ""}
  ${captions.html}
  ${hook?.html ?? ""}
  ${graphics.html}
  ${cortinilla?.html ?? ""}
  ${outro?.html ?? ""}
  ${sfx.join("\n  ")}
</div>
<script>
const tl = gsap.timeline({ paused: true });
${treatment.script}
${captions.script}
${hook?.script ?? ""}
${graphics.script}
${cortinilla?.script ?? ""}
${outro?.script ?? ""}
tl.set({}, {}, ${total});
window.__timelines = window.__timelines || {};
window.__timelines["root"] = tl;
tl.seek(0);
</script>
</body></html>`;
  writeFileSync(join(workDir, "index.html"), html);
  return { entryFile: "index.html", projectDir: workDir, total };
}
