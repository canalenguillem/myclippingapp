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

