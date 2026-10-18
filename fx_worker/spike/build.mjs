// Genera un proyecto HyperFrames (index.html + medios) a partir de un payload de prueba.
// Es un EXPERIMENTO: comprueba que cada pieza del estilo se puede hacer con HyperFrames. No es el servicio final.
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const nm = join(here, "..", "node_modules");

export const PAYLOAD = {
  fps: 30,
  sourceSeconds: 32, // duración del clip de origen
  cortinilla: { at: 4.0, duration: 3.6, title: "Spain", accent: "Facts" }, // `at` en segundos del ORIGEN
  outro: { duration: 2.5 },
  hook: "NADIE SE LO ESPERABA",
  keyword: { at: 10.2, text: "INDULTOS" }, // segundo del origen
  words: (
    "Urgente Pedro Sánchez activa la trampa en el Tribunal Constitucional de Cándido Conde Pumpido para que " +
    "puedan votar todos los nacionalizados con la Ley de Nietos en las elecciones generales Muy buenas a todos " +
    "y bienvenidos a una nueva edición especial urgente de Medidas Cautelares"
  ).split(" ").map((text, i) => ({ text, start: +(0.5 + i * 0.5).toFixed(2), end: +(0.5 + i * 0.5 + 0.4).toFixed(2) })),
};

const RED = "#DA2E09", PAPER = "#F3EEE2", INK = "#1D1A17";

export function buildProject(outDir, payload = PAYLOAD) {
  const { cortinilla: C, outro: O } = payload;
  // Mapa de tiempos único: t_salida = t_origen + duración de la cortinilla si ya pasó el corte.
  const T = (t) => +(t >= C.at ? t + C.duration : t).toFixed(3);
  const outroStart = payload.sourceSeconds + C.duration;
  const total = +(outroStart + O.duration).toFixed(3);

  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(join(outDir, "fonts"), { recursive: true });
  for (const f of ["source.mp4", "whoosh.wav", "pop.wav", "music.wav"]) cpSync(join(here, "assets", f), join(outDir, f));
  cpSync(join(nm, "gsap", "dist", "gsap.min.js"), join(outDir, "gsap.min.js"));
  cpSync(join(nm, "@fontsource/inter/files/inter-latin-800-normal.woff2"), join(outDir, "fonts/inter-800.woff2"));
  cpSync(join(nm, "@fontsource/cormorant/files/cormorant-latin-600-italic.woff2"), join(outDir, "fonts/cormorant-600i.woff2"));

  // Fotogramas congelados bajo los barridos (§6 del md): último fotograma del tramo 1 y primero del tramo 2.
  const still = (name, at) => {
    const r = spawnSync("ffmpeg", ["-v", "error", "-y", "-ss", String(at), "-i", join(here, "assets", "source.mp4"), "-frames:v", "1", join(outDir, name)]);
    if (r.status !== 0) throw new Error(`ffmpeg no pudo extraer ${name}: ${r.stderr}`);
  };
  still("freezeA.png", +(C.at - 1 / payload.fps).toFixed(3));
  still("freezeB.png", C.at);
  const SW = 0.42; // duración de cada barrido

  // Frases de 3 palabras; nunca cruzan el corte de la cortinilla.
  const groups = [];
  let cur = [];
  for (const w of payload.words) {
    const crosses = cur.length && cur[cur.length - 1].start < C.at && w.start >= C.at;
    if (cur.length === 3 || crosses) { groups.push(cur); cur = []; }
    cur.push(w);
  }
  if (cur.length) groups.push(cur);

  const phraseHtml = groups.map((g, gi) =>
    `<div class="phrase" id="p${gi}">${g.map((w, wi) => `<span class="w" id="w${gi}_${wi}">${w.text.toUpperCase()}</span>`).join(" ")}</div>`).join("\n");

  // Perímetro de la píldora y punto sobre ella por longitud de arco (para la órbita).
  const PW = 900, PH = 300, R = PH / 2, straight = PW - PH, arc = Math.PI * R;
  const perim = 2 * straight + 2 * arc;
  const pillPoint = (s) => {
    s = ((s % perim) + perim) % perim;
    if (s < straight) return [540 - straight / 2 + s, 960 - R];
    s -= straight;
    if (s < arc) { const a = -Math.PI / 2 + (s / arc) * Math.PI; return [540 + straight / 2 + R * Math.cos(a), 960 + R * Math.sin(a)]; }
    s -= arc;
    if (s < straight) return [540 + straight / 2 - s, 960 + R];
    s -= straight;
    const a = Math.PI / 2 + (s / arc) * Math.PI;
    return [540 - straight / 2 + R * Math.cos(a), 960 + R * Math.sin(a)];
  };

  const c0 = C.at, c1 = c0 + C.duration;
  const orbitSets = [];
  for (let t = c0 + 0.95; t < c0 + 2.75; t += 1 / payload.fps) {
    const [x, y] = pillPoint((t - (c0 + 0.95)) * 0.30 * perim);
    orbitSets.push(`tl.set("#orbit",{x:${(x - 75).toFixed(1)},y:${(y - 75).toFixed(1)}},${t.toFixed(3)});`);
  }

  const kw = T(payload.keyword.at);
  const script = `
const tl = gsap.timeline({ paused: true });
// --- hook: entrada desenfocada (filter: blur) ---
tl.fromTo("#hook",{opacity:0,y:40,filter:"blur(24px)"},{opacity:1,y:0,filter:"blur(0px)",duration:0.5,ease:"power3.out"},0.1);
tl.to("#hook",{opacity:0,duration:0.3,ease:"power3.in"},2.4);
// --- subtítulos karaoke ---
${groups.map((g, gi) => {
  const s = T(g[0].start) - 0.04;
  const e = Math.min(T(g[g.length - 1].end) + 0.25, g[g.length - 1].start < C.at ? c0 : 1e9);
  return `tl.fromTo("#p${gi}",{opacity:0,y:6},{opacity:1,y:0,duration:0.14},${s.toFixed(3)});tl.set("#p${gi}",{opacity:0},${e.toFixed(3)});` +
    g.map((w, wi) => `tl.set("#w${gi}_${wi}",{color:"${RED}"},${T(w.start)});tl.fromTo("#w${gi}_${wi}",{scale:1.05},{scale:1,duration:0.15},${T(w.start)});`).join("");
}).join("\n")}
// --- tarjeta de palabra clave: pop con rebote ---
tl.fromTo("#kw",{opacity:0,scale:0.55,y:40},{opacity:1,scale:1,y:0,duration:0.42,ease:"back.out(1.7)"},${(kw - 0.3).toFixed(3)});
tl.to("#kw",{opacity:0,scale:0.7,duration:0.3,ease:"power3.in"},${(kw + 2.2).toFixed(3)});
// --- cortinilla: barrido curvo, texto desenfocado, línea que dibuja la píldora, objeto que orbita ---
tl.fromTo("#sweep",{x:-1560},{x:0,duration:0.42,ease:"power2.inOut"},${c0});
tl.fromTo("#t1",{opacity:0,y:24,filter:"blur(14px)"},{opacity:1,y:0,filter:"blur(0px)",duration:0.45,ease:"power3.out"},${(c0 + 0.30).toFixed(3)});
tl.fromTo("#t2",{opacity:0,y:24,filter:"blur(14px)"},{opacity:1,y:0,filter:"blur(0px)",duration:0.45,ease:"power3.out"},${(c0 + 0.48).toFixed(3)});
tl.fromTo("#pill",{strokeDashoffset:${perim.toFixed(1)}},{strokeDashoffset:0,duration:0.95,ease:"power1.inOut"},${(c0 + 0.55).toFixed(3)});
tl.fromTo("#orbit",{opacity:0,scale:0},{opacity:1,scale:1,duration:0.35,ease:"back.out(2.2)"},${(c0 + 0.95).toFixed(3)});
${orbitSets.join("\n")}
tl.to("#pill",{strokeDashoffset:${(-perim).toFixed(1)},duration:0.45,ease:"power1.in"},${(c0 + 2.7).toFixed(3)});
tl.to(["#t1","#t2","#orbit"],{opacity:0,filter:"blur(10px)",duration:0.45,ease:"power3.in"},${(c0 + 2.75).toFixed(3)});
tl.to("#sweep",{x:1560,duration:0.42,ease:"power2.inOut"},${(c1 - 0.42).toFixed(3)});
// --- cortinilla final ---
tl.fromTo("#sweep2",{x:-1560},{x:0,duration:0.42,ease:"power2.inOut"},${outroStart});
tl.fromTo("#paper",{opacity:0},{opacity:1,duration:0.4,ease:"power1.out"},${(outroStart + 0.45).toFixed(3)});
tl.fromTo("#cta",{opacity:0,scale:0.6},{opacity:1,scale:1,duration:0.5,ease:"back.out(1.8)"},${(outroStart + 0.5).toFixed(3)});
tl.set({}, {}, ${total});
window.__timelines = window.__timelines || {};
window.__timelines["root"] = tl;
tl.seek(0);`;

  const sweepSvg = (id, fill) => `
    <svg id="${id}" class="sweep" width="1560" height="1920" viewBox="0 0 1560 1920">
      <path d="M0 0 H1230 Q1560 960 1230 1920 H0 Z" fill="#fff" transform="translate(46 0)"/>
      <path d="M0 0 H1230 Q1560 960 1230 1920 H0 Z" fill="${fill}"/>
    </svg>`;

  const html = `<!doctype html>
<html lang="es"><head><meta charset="UTF-8"/><meta name="viewport" content="width=1080, height=1920"/>
<script src="gsap.min.js"></script>
<style>
@font-face{font-family:"InterX";font-weight:800;src:url(fonts/inter-800.woff2) format("woff2")}
@font-face{font-family:"CormorantX";font-weight:600;font-style:italic;src:url(fonts/cormorant-600i.woff2) format("woff2")}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1920px;overflow:hidden;background:#000}
#root{position:relative;width:1080px;height:1920px;overflow:hidden;font-family:InterX,sans-serif}
.vid{position:absolute;inset:0;width:1080px;height:1920px;object-fit:cover}
#band{position:absolute;left:0;top:1400px;width:1080px;height:130px;background:${PAPER};box-shadow:0 4px 4px rgba(0,0,0,.4)}
#caps{position:absolute;left:0;top:1400px;width:1080px;height:130px}
.phrase{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;gap:18px;opacity:0;font-weight:800;font-size:64px;color:${INK}}
.w{display:inline-block;color:rgba(29,26,23,.38)}
#hook{position:absolute;left:0;right:0;top:140px;text-align:center;font-weight:800;font-size:88px;color:#fff;text-shadow:0 6px 18px rgba(0,0,0,.6);opacity:0}
#kw{position:absolute;left:290px;top:520px;width:500px;height:230px;border-radius:26px;background:${PAPER};box-shadow:0 12px 14px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;opacity:0}
#kw b{position:absolute;left:0;top:0;bottom:0;width:18px;background:${RED};border-radius:26px 0 0 26px}
#kw span{font-weight:800;font-size:68px;color:${INK}}
#cort,#outro{position:absolute;inset:0}
.sweep{position:absolute;left:0;top:0;will-change:transform}
#t1,#t2{position:absolute;color:#fff;opacity:0}
#t1{left:230px;top:905px;font-weight:800;font-size:116px}
#t2{left:615px;top:880px;font-family:CormorantX,serif;font-style:italic;font-weight:600;font-size:138px}
#pillsvg{position:absolute;left:0;top:0}
#orbit{position:absolute;left:0;top:0;width:150px;height:150px;border-radius:22px;background:#fff;box-shadow:0 10px 14px rgba(0,0,0,.35);opacity:0}
#orbit i{position:absolute;inset:30px;background:${RED};border-radius:10px}
#outro .stage{position:absolute;inset:0;background:${PAPER}}
#cta{position:absolute;left:190px;top:820px;width:700px;text-align:center;opacity:0}
#cta .btn{display:inline-block;margin:16px;padding:26px 54px;border-radius:60px;background:${RED};color:#fff;font-weight:800;font-size:54px}
#cta .big{font-family:CormorantX,serif;font-style:italic;font-weight:600;font-size:110px;color:${INK}}
</style></head>
<body>
<div id="root" data-composition-id="root" data-start="0" data-duration="${total}" data-width="1080" data-height="1920">
  <video id="vA" class="clip vid" src="source.mp4" data-start="0" data-duration="${c0}" data-media-start="0" data-track-index="0" data-has-audio="true" playsinline></video>
  <video id="vB" class="clip vid" src="source.mp4" data-start="${c1}" data-duration="${(payload.sourceSeconds - c0).toFixed(3)}" data-media-start="${c0}" data-track-index="0" data-has-audio="true" playsinline></video>
  <img id="fzA" class="clip vid" src="freezeA.png" data-start="${c0}" data-duration="${SW}" data-track-index="0"/>
  <img id="fzB" class="clip vid" src="freezeB.png" data-start="${(c1 - SW).toFixed(3)}" data-duration="${SW}" data-track-index="0"/>
  <div id="band" class="clip" data-start="0" data-duration="${(c0 + SW).toFixed(3)}" data-track-index="1"></div>
  <div id="band2" class="clip" data-start="${(c1 - SW).toFixed(3)}" data-duration="${(payload.sourceSeconds - c0 + SW).toFixed(3)}" data-track-index="1" style="position:absolute;left:0;top:1400px;width:1080px;height:130px;background:${PAPER};box-shadow:0 4px 4px rgba(0,0,0,.4)"></div>
  <div id="caps">${phraseHtml}</div>
  <div id="hook">${payload.hook}</div>
  <div id="kw"><b></b><span>${payload.keyword.text}</span></div>
  <div id="cort" class="clip" data-start="${c0}" data-duration="${C.duration}" data-track-index="5">
    ${sweepSvg("sweep", RED)}
    <div id="t1">${C.title}</div><div id="t2">${C.accent}</div>
    <svg id="pillsvg" width="1080" height="1920" viewBox="0 0 1080 1920"><rect id="pill" x="${540 - PW / 2}" y="${960 - PH / 2}" width="${PW}" height="${PH}" rx="${R}" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-dasharray="${perim.toFixed(1)}" stroke-dashoffset="${perim.toFixed(1)}"/></svg>
    <div id="orbit"><i></i></div>
  </div>
  <div id="outro" class="clip" data-start="${outroStart}" data-duration="${O.duration}" data-track-index="5">
    ${sweepSvg("sweep2", RED)}
    <div class="stage" id="paper" style="opacity:0"></div>
    <div id="cta"><div class="big">Suscríbete</div><span class="btn">ME GUSTA</span><span class="btn">SUSCRÍBETE</span></div>
  </div>
  <audio id="music" src="music.wav" data-start="0" data-duration="${total}" data-volume="0.10" data-fade-out="1.5"></audio>
  <audio id="whoosh1" src="whoosh.wav" data-start="${c0}" data-duration="0.7" data-volume="0.45"></audio>
  <audio id="whoosh2" src="whoosh.wav" data-start="${(c1 - 0.42).toFixed(3)}" data-duration="0.7" data-volume="0.45"></audio>
  <audio id="whoosh3" src="whoosh.wav" data-start="${outroStart}" data-duration="0.7" data-volume="0.45"></audio>
  <audio id="pop1" src="pop.wav" data-start="${(kw - 0.3).toFixed(3)}" data-duration="0.12" data-volume="0.5"></audio>
</div>
<script>${script}</script>
</body></html>`;
  writeFileSync(join(outDir, "index.html"), html);
  return { total, perim, outDir };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const r = buildProject(join(here, "project"));
  console.log("proyecto generado:", r);
}
