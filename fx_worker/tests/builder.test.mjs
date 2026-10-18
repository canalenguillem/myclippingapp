import assert from "node:assert/strict";
import { existsSync, lstatSync, readFileSync, realpathSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { buildProject } from "../src/builder.mjs";
import { parseRequest } from "../src/contract.mjs";
import { groupPhrases } from "../src/layers/captions.mjs";
import { checkProject } from "../src/render.mjs";
import { makeVideo, tmp } from "./helpers.mjs";

const w = (text, start, end) => ({ text, start, end });
const base = { video: "a.mp4", output: "b.mp4", duration: 3 };

test("groupPhrases: máximo 3 palabras, corte tras puntuación y tras pausa, y descarta lo que pasa del final", () => {
  const g = groupPhrases([w("uno", 0, 0.3), w("dos", 0.4, 0.7), w("tres", 0.8, 1.1), w("cuatro", 1.2, 1.5)], 5);
  assert.deepEqual(g.map((x) => x.map((y) => y.text)), [["uno", "dos", "tres"], ["cuatro"]]);
  const p = groupPhrases([w("Hola.", 0, 0.3), w("Adiós", 0.4, 0.7)], 5);
  assert.deepEqual(p.map((x) => x.length), [1, 1]);
  const gap = groupPhrases([w("a", 0, 0.3), w("b", 1.5, 1.8)], 5);
  assert.equal(gap.length, 2);
  const cut = groupPhrases([w("a", 0, 0.3), w("fuera", 6, 6.3)], 5);
  assert.deepEqual(cut.flat().map((x) => x.text), ["a"]);
});

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
