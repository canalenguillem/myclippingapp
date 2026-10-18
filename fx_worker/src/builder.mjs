// Genera el proyecto HyperFrames de un render: index.html + medios, en un directorio de trabajo propio.
import { copyFileSync, cpSync, mkdirSync, symlinkSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { captionsLayer } from "./layers/captions.mjs";

const require = createRequire(import.meta.url);

const assetPath = (spec) => require.resolve(spec);

/** `video` es la ruta ABSOLUTA ya resuelta (y comprobada) del clip vertical. */
export function buildProject({ request, video, workDir }) {
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

  const { duration, layout, words } = request;
  const captions = captionsLayer({ words, duration, layout });
  const total = Number(duration.toFixed(3));

  const html = `<!doctype html>
<html lang="es"><head><meta charset="UTF-8"/><meta name="viewport" content="width=1080, height=1920"/>
<script src="gsap.min.js"></script>
<style>
@font-face{font-family:"InterX";font-weight:800;src:url(fonts/inter-800.woff2) format("woff2")}
@font-face{font-family:"CormorantX";font-weight:600;font-style:italic;src:url(fonts/cormorant-600i.woff2) format("woff2")}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1920px;overflow:hidden;background:#000}
#root{position:relative;width:1080px;height:1920px;overflow:hidden}
.vid{position:absolute;inset:0;width:1080px;height:1920px;object-fit:cover}
${captions.css}
</style></head>
<body>
<div id="root" data-composition-id="root" data-start="0" data-duration="${total}" data-width="1080" data-height="1920">
  <video id="clip" class="clip vid" src="clip.mp4" data-start="0" data-duration="${total}" data-media-start="0" data-track-index="0" data-has-audio="true" playsinline></video>
  ${captions.html}
</div>
<script>
const tl = gsap.timeline({ paused: true });
${captions.script}
tl.set({}, {}, ${total});
window.__timelines = window.__timelines || {};
window.__timelines["root"] = tl;
tl.seek(0);
</script>
</body></html>`;
  writeFileSync(join(workDir, "index.html"), html);
  return { entryFile: "index.html", projectDir: workDir, total };
}
