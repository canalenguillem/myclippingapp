import assert from "node:assert/strict";
import { test } from "node:test";
import { ContractError, isSafeRel, parseRequest } from "../src/contract.mjs";

const base = { video: "u1/p1/clip.mp4", output: "u1/p1/draft.mp4", duration: 12.5 };

test("una petición mínima recibe los valores por defecto", () => {
  const r = parseRequest(base);
  assert.equal(r.quality, "standard");
  assert.equal(r.fps, 30);
  assert.deepEqual(r.layout, { mode: "split", top_ratio: 0.5 });
  assert.equal(r.preset, "editorial");
  assert.deepEqual(r.words, []);
});

test("acepta palabras, speakers y gancho completos", () => {
  const r = parseRequest({
    ...base,
    quality: "draft",
    words: [{ text: "Hola", start: 0.2, end: 0.6, speaker: "A" }],
    speakers: { A: { name: "Ana", caption_style: "serif_italic", is_source: true } },
    hook: { text: "Nadie se lo esperaba" },
  });
  assert.equal(r.speakers.A.role, "");
  assert.equal(r.hook.duration, 2);
});

test("rutas inseguras", () => {
  for (const bad of ["../x.mp4", "/etc/passwd.mp4", "a/../../x.mp4", "a\\b.mp4", "a//b.mp4", "./a.mp4", "", "a/\u0000b.mp4"]) {
    assert.equal(isSafeRel(bad), false, JSON.stringify(bad));
    assert.throws(() => parseRequest({ ...base, video: bad }), ContractError, JSON.stringify(bad));
  }
  assert.equal(isSafeRel("u1/p3/clip_12/vertical.mp4"), true);
});

test("el vídeo y la salida deben ser .mp4", () => {
  assert.throws(() => parseRequest({ ...base, video: "u1/clip.mov" }), ContractError);
  assert.throws(() => parseRequest({ ...base, output: "u1/out.png" }), ContractError);
});

test("valores fuera de rango o desconocidos", () => {
  const bads = [
    { duration: 0 }, { duration: 601 }, { duration: -1 }, { quality: "ultra" }, { fps: 25 },
    { layout: { mode: "full" } }, { layout: { mode: "split", top_ratio: 0.1 } }, { preset: "otro" },
    { words: [{ text: "x", start: 2, end: 1 }] }, { words: [{ text: "", start: 0, end: 1 }] },
    { words: [{ text: "x", start: -1, end: 1 }] }, { words: [{ text: "x", start: 0, end: 1, color: "red" }] },
    { speakers: { "A b": {} } }, { speakers: { A: { caption_style: "comic" } } },
    { hook: { text: "x", duration: 10 } }, { hook: { text: "" } }, { extra: 1 },
  ];
  for (const bad of bads) assert.throws(() => parseRequest({ ...base, ...bad }), ContractError, JSON.stringify(bad));
});

test("límite de palabras", () => {
  const words = Array.from({ length: 5001 }, (_, i) => ({ text: "a", start: i, end: i + 0.1 }));
  assert.throws(() => parseRequest({ ...base, words }), ContractError);
});

test("el error de contrato lista los campos", () => {
  try {
    parseRequest({ ...base, duration: -3, quality: "x" });
    assert.fail("debía lanzar");
  } catch (e) {
    assert.ok(e instanceof ContractError);
    assert.ok(e.details.some((d) => d.startsWith("duration")) && e.details.some((d) => d.startsWith("quality")));
  }
});
