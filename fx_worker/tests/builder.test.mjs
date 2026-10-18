import assert from "node:assert/strict";
import { existsSync, lstatSync, readFileSync, realpathSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { buildProject } from "../src/builder.mjs";
import { parseRequest } from "../src/contract.mjs";
import { checkProject } from "../src/render.mjs";
import { makeVideo, tmp } from "./helpers.mjs";

const w = (text, start, end) => ({ text, start, end });
const base = { video: "a.mp4", output: "b.mp4", duration: 3 };

test("construye un proyecto válido: estructura, GSAP y fuentes locales, vídeo con audio y sin red", async () => {
  const dir = tmp();
  const video = makeVideo(join(dir, "src.mp4"), 3);
  const request = parseRequest({ ...base, words: [w("Hola", 0.2, 0.6), w("mundo", 0.7, 1.1)] });
  const work = join(dir, "work");
  const r = buildProject({ request, video, workDir: work });
  const html = readFileSync(join(r.projectDir, r.entryFile), "utf8");
  for (const needle of ['data-composition-id="root"', 'data-width="1080"', 'data-height="1920"', 'data-has-audio="true"', 'data-duration="3"', "tl.set({}, {}, 3)", 'window.__timelines["root"] = tl']) {
    assert.ok(html.includes(needle), needle);
  }
  assert.ok(!/https?:\/\//.test(html), "la composición no debe cargar nada de la red");
  for (const f of ["gsap.min.js", "fonts/inter-800.woff2", "fonts/cormorant-600i.woff2", "clip.mp4"]) assert.ok(existsSync(join(work, f)), f);
  assert.equal(realpathSync(join(work, "clip.mp4")), realpathSync(video)); // enlace, no copia
  assert.ok(lstatSync(join(work, "clip.mp4")).isSymbolicLink());
  const ids = [...html.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
  assert.equal(new Set(ids).size, ids.length, "ids duplicados");
});

test("el texto de las palabras se escapa (viene del usuario)", () => {
  const dir = tmp();
  const video = makeVideo(join(dir, "src.mp4"), 2);
  const request = parseRequest({ ...base, duration: 2, words: [w('<img src=x onerror="alert(1)">', 0, 0.5), w("</script><b>", 0.6, 1)] });
  const r = buildProject({ request, video, workDir: join(dir, "work") });
  const html = readFileSync(join(r.projectDir, "index.html"), "utf8");
  assert.ok(!html.includes("<img src=x") && !html.includes("<b>"));
  assert.ok(html.includes("&lt;IMG SRC=X") || html.includes("&lt;img"));
  assert.equal((html.match(/<script/g) ?? []).length, 2); // solo gsap y el nuestro
});

test("el linter de HyperFrames no encuentra errores", async () => {
  const dir = tmp();
  const video = makeVideo(join(dir, "src.mp4"), 3);
  const request = parseRequest({ ...base, words: [w("Hola", 0.2, 0.6), w("mundo", 0.7, 1.1), w("otra", 1.5, 1.9)] });
  const r = buildProject({ request, video, workDir: join(dir, "work") });
  const result = await checkProject(r.projectDir); // lanza si hay errores (p. ej. un <audio> sin id saldría mudo)
  assert.equal(result.totalErrors, 0);
});

test("sin palabras también compila y pasa el linter", async () => {
  const dir = tmp();
  const video = makeVideo(join(dir, "src.mp4"), 2);
  const r = buildProject({ request: parseRequest({ ...base, duration: 2 }), video, workDir: join(dir, "work") });
  await checkProject(r.projectDir);
});

const spk = {
  A: { name: "Ana", role: "", caption_style: "sans_upper", is_source: false },
  B: { name: "Bea", role: "", caption_style: "serif_italic", is_source: true },
};
const ws = [
  { text: "Hola", start: 0.2, end: 0.6, speaker: "A" },
  { text: "mundo", start: 0.7, end: 1.1, speaker: "A" },
  { text: "cita", start: 1.8, end: 2.2, speaker: "B" },
  { text: "textual", start: 2.3, end: 2.8, speaker: "B" },
];
const build = (extra = {}, name = "w") => {
  const dir = tmp();
  const video = makeVideo(join(dir, "src.mp4"), 4);
  const request = parseRequest({ video: "a.mp4", output: "b.mp4", duration: 4, words: ws, speakers: spk, ...extra });
  const r = buildProject({ request, video, workDir: join(dir, name) });
  return { html: readFileSync(join(r.projectDir, "index.html"), "utf8"), projectDir: r.projectDir };
};

test("cada frase usa el estilo de su speaker", () => {
  const { html } = build();
  assert.match(html, /<div class="phrase sans" id="p0"[^>]*>.*HOLA.*MUNDO/);
  assert.match(html, /<div class="phrase serif" id="p1"[^>]*>.*cita.*textual/); // serif cursiva: sin pasar a mayúsculas
});

test("la banda solo existe en el preset editorial y cubre las filas pedidas con 10 px de margen", () => {
  const a = build({ band: { y0: 1700, y1: 1780 } });
  assert.ok(a.html.includes('<svg id="band"'));
  assert.ok(a.html.includes(`top:${1700 - 10 - 30}px`), "svg 30 px por encima de la zona protegida con margen");
  assert.ok(!build({ preset: "hormozi" }).html.includes('id="band"'));
  assert.ok(!build({ preset: "minimal" }).html.includes('id="band"'));
  const centered = build();
  assert.ok(centered.html.includes(`top:${960 - 45 - 30}px`), "sin `band` va centrada en el corte (top_ratio 0,5)");
});

test("el blanco y negro solo aparece si algún speaker es is_source", () => {
  const { html } = build();
  assert.ok(html.includes('"#vwrap"') && html.includes("grayscale(1)"));
  assert.ok(!html.includes("data-color-grading"), "sin el tratamiento WebGL de HyperFrames (inviable sin GPU)");
  const none = build({ speakers: { A: spk.A, B: { ...spk.B, is_source: false } } });
  assert.ok(!none.html.includes("grayscale"));
});

test("el gancho entra en la composición, escapado, con la última palabra como acento", () => {
  const { html } = build({ hook: { text: "Nadie <b>se</b> lo esperaba", duration: 2 } });
  assert.ok(!html.includes("<b>se"));
  assert.match(html, /<div id="hook">.*&lt;B&gt;SE&lt;\/B&gt; LO <span class="acc">ESPERABA<\/span>/);
  assert.ok(!build().html.includes('id="hook"'));
});

test("todas las combinaciones de capas pasan el linter de HyperFrames", async () => {
  for (const [name, extra] of [
    ["editorial", { hook: { text: "Nadie se lo esperaba" }, band: { y0: 1380, y1: 1470 } }],
    ["hormozi", { preset: "hormozi", hook: { text: "Gancho corto" } }],
    ["minimal", { preset: "minimal" }],
  ]) {
    const { projectDir } = build(extra, name);
    const result = await checkProject(projectDir);
    assert.equal(result.totalErrors, 0, name);
  }
});



test("con cortinilla: dos tramos del clip, fotogramas congelados, duración total y palabras desplazadas", async () => {
  const dir = tmp();
  const video = makeVideo(join(dir, "src.mp4"), 6);
  const request = parseRequest({
    video: "a.mp4", output: "b.mp4", duration: 6, cortinilla: { at: 3, duration: 3.6 },
    words: [{ text: "antes", start: 1, end: 1.4 }, { text: "despues", start: 3.5, end: 4 }],
  });
  const work = join(dir, "work");
  const r = buildProject({ request, video, workDir: work });
  const html = readFileSync(join(work, "index.html"), "utf8");
  assert.equal(r.total, 9.6);
  assert.match(html, /id="clipA"[^>]*data-start="0" data-duration="3" data-media-start="0"/);
  assert.match(html, /id="clipB"[^>]*data-start="6.6" data-duration="3" data-media-start="3"/);
  assert.match(html, /id="freezeA"[^>]*data-start="3" data-duration="0.42"/);
  assert.match(html, /id="freezeB"[^>]*data-start="6.18" data-duration="0.42"/);
  assert.match(html, /id="cort" class="clip" data-start="3" data-duration="3.6"/);
  assert.ok(html.includes('data-duration="9.6" data-width="1080"') && html.includes("tl.set({}, {}, 9.6)"));
  for (const f of ["freezeA.png", "freezeB.png"]) assert.ok(existsSync(join(work, f)), f);
  assert.ok(html.includes('tl.set("#w1_0",{color:"#DA2E09"},7.1)'), "«despues» (3,5 s del clip) suena a los 7,1 s de salida");
  assert.ok(!html.includes('id="clip"'), "con cortinilla no hay un único vídeo");
  const ids = [...html.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
  assert.equal(new Set(ids).size, ids.length, "ids duplicados");
  assert.equal((await checkProject(work)).totalErrors, 0);
});

test("la frase anterior a la cortinilla se oculta al empezar y el blanco y negro no la cruza", () => {
  const dir = tmp();
  const video = makeVideo(join(dir, "src.mp4"), 6);
  const request = parseRequest({
    video: "a.mp4", output: "b.mp4", duration: 6, cortinilla: { at: 2.1, duration: 3.6 },
    speakers: { B: { caption_style: "serif_italic", is_source: true } },
    words: [{ text: "cita", start: 1.0, end: 2.0, speaker: "B" }, { text: "larga", start: 2.2, end: 3.0, speaker: "B" }],
  });
  const work = join(dir, "work");
  buildProject({ request, video, workDir: work });
  const html = readFileSync(join(work, "index.html"), "utf8");
  assert.ok(html.includes('tl.set("#p0",{opacity:0},2.1)'), "la frase 0 se oculta cuando entra la cortinilla (no a los 2,25 s)");
  assert.equal((html.match(/grayscale\(1\)/g) ?? []).length, 2, "el tramo en B/N se parte en dos, sin cubrir la cortinilla");
});
