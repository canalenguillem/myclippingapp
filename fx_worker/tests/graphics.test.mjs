import assert from "node:assert/strict";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { buildProject } from "../src/builder.mjs";
import { ContractError, parseRequest } from "../src/contract.mjs";
import { graphicWindow, graphicZones, graphicsLayer } from "../src/layers/graphics.mjs";
import { keywordMotif, keywordSize } from "../src/motifs/keyword.mjs";
import { checkProject } from "../src/render.mjs";
import { makeTimeMap } from "../src/timemap.mjs";
import { makeVideo, tmp } from "./helpers.mjs";

const base = { video: "a.mp4", output: "b.mp4", duration: 20 };
const kw = (extra = {}) => ({ type: "keyword", at: 8, text: "Indultos", ...extra });

test("contrato: valores por defecto, texto recortado y validaciones", () => {
  const g = parseRequest({ ...base, graphics: [kw({ text: "  Indultos " })] }).graphics[0];
  assert.deepEqual(g, { type: "keyword", at: 8, lead: 0.5, duration: 2.5, text: "Indultos", zone: "bottom" });
  assert.deepEqual(parseRequest(base).graphics, []);
  for (const bad of [kw({ type: "otro" }), kw({ text: "" }), kw({ text: "x".repeat(41) }), kw({ at: -1 }), kw({ lead: 2 }), kw({ duration: 0.2 }), kw({ extra: 1 })])
    assert.throws(() => parseRequest({ ...base, graphics: [bad] }), ContractError, JSON.stringify(bad));
  assert.throws(() => parseRequest({ ...base, graphics: [kw({ at: 25 })] }), /fuera del clip/);
});

test("contrato: un gráfico no puede cruzar la cortinilla de inicio, pero sí estar antes o después", () => {
  const cort = { at: 10 };
  assert.throws(() => parseRequest({ ...base, cortinilla: cort, graphics: [kw({ at: 10.2 })] }), /cruzar la cortinilla/);  // ventana 9,7–12,2
  assert.doesNotThrow(() => parseRequest({ ...base, cortinilla: cort, graphics: [kw({ at: 7 }), kw({ at: 11, lead: 0.5 })] }));
});

test("la ventana: entra `lead` antes, vive `duration` y se acota al clip", () => {
  assert.deepEqual(graphicWindow({ at: 8, lead: 0.5, duration: 2.5 }, 20), [7.5, 10]);
  assert.deepEqual(graphicWindow({ at: 0.2, lead: 0.5, duration: 2.5 }, 20), [0, 2.5]);
  assert.deepEqual(graphicWindow({ at: 19, lead: 0.5, duration: 3 }, 20), [18.5, 20]);
});

test("la capa aplica el mapa de tiempos: lo posterior a la cortinilla se desplaza y el efecto va con el gráfico", () => {
  const items = [{ type: "keyword", at: 4, lead: 0.5, duration: 2.5, text: "A" }, { type: "keyword", at: 14, lead: 0.5, duration: 2.5, text: "B" }];
  const out = graphicsLayer({ items, map: makeTimeMap({ at: 8, duration: 3.6 }), clipDuration: 20 });
  assert.ok(out.script.includes('},3.5);') && out.script.includes('},17.1);'), "A a 3,5 s y B a 13,5 + 3,6 = 17,1 s");
  assert.deepEqual(out.sfx, [{ id: "sfxg0", kind: "pop", at: 3.5 }, { id: "sfxg1", kind: "pop", at: 17.1 }]);
  assert.equal(graphicsLayer({ items: [], map: makeTimeMap(undefined), clipDuration: 20 }).html, "");
});

test("keyword: texto escapado en mayúsculas, tamaño ajustado y salida antes del final", () => {
  const m = keywordMotif({ id: "g0", item: { text: "<b>Hola</b>" }, t0: 1, at: 1.5, t1: 3.5, zones: graphicZones({ mode: "split" }) });
  assert.ok(!m.html.includes("<b>Hola") && m.html.includes("&lt;B&gt;HOLA&lt;/B&gt;"));
  assert.equal(keywordSize("INDULTOS"), 68);
  assert.ok(keywordSize("UNA PALABRA CLAVE MUY LARGA SIN CABER") < 68 && keywordSize("X".repeat(40)) >= 40);
  assert.ok(m.script.includes('},3.2);') && m.script.includes('visibility:"hidden"},3.5'));
});

test("builder: el gráfico entra en la composición con su sonido, sin red, y pasa el linter", async () => {
  const dir = tmp();
  const video = makeVideo(join(dir, "src.mp4"), 12);
  const request = parseRequest({ video: "a.mp4", output: "b.mp4", duration: 12, graphics: [kw({ at: 3, text: "Indultos" })] });
  const work = join(dir, "work");
  buildProject({ request, video, workDir: work });
  const html = readFileSync(join(work, "index.html"), "utf8");
  assert.ok(html.includes('id="g0" class="gfx kw"') && html.includes("INDULTOS"));
  assert.match(html, /<audio id="sfxg0" src="sfx\/pop.wav" data-start="2.5" data-duration="0.12" data-volume="0.3">/);
  assert.equal((await checkProject(work)).totalErrors, 0);
  // sfx: false → sin audio de gráficos
  const off = join(dir, "off");
  buildProject({ request: parseRequest({ video: "a.mp4", output: "b.mp4", duration: 12, sfx: false, graphics: [kw({ at: 3 })] }), video, workDir: off });
  assert.ok(!readFileSync(join(off, "index.html"), "utf8").includes("<audio"));
});

import { emojiMotif } from "../src/motifs/emoji.mjs";

test("emoji: solo se aceptan emojis (nada de texto ni HTML) y el objetivo es opcional", () => {
  const ok = parseRequest({ ...base, graphics: [{ type: "emoji", at: 8, emoji: "🐔", target: "🗳️" }] }).graphics[0];
  assert.deepEqual([ok.emoji, ok.target, ok.lead, ok.duration], ["🐔", "🗳️", 0.5, 2.5]);
  assert.equal(parseRequest({ ...base, graphics: [{ type: "emoji", at: 8, emoji: "👍🏽" }] }).graphics[0].target, undefined);
  for (const bad of ["abc", "<b>", "🐔x", "", "1"]) assert.throws(() => parseRequest({ ...base, graphics: [{ type: "emoji", at: 8, emoji: bad }] }), ContractError, bad);
  assert.throws(() => parseRequest({ ...base, graphics: [{ type: "emoji", at: 8, emoji: "🐔", target: "hola" }] }), ContractError);
});

test("emoji con objetivo: la llegada cae en la palabra y el objetivo rebota; sin objetivo, pop y salto", () => {
  const scene = emojiMotif({ id: "g1", item: { emoji: "🐔", target: "🗳️" }, t0: 10, at: 11, t1: 13, zones: graphicZones({ mode: "split" }) });
  assert.ok(scene.html.includes('id="g1m"') && scene.html.includes('id="g1t"') && scene.html.includes("🐔") && scene.html.includes("🗳️"));
  assert.ok(scene.script.includes('{scale:1.28,duration:0.12,ease:"power2.out",yoyo:true,repeat:1},11);'), "el objetivo rebota en la palabra (11 s)");
  assert.equal((scene.script.match(/ease:"none"/g) ?? []).length, 3, "tres saltos");
  assert.ok(scene.script.includes("scaleX:-1") && scene.cssItem.includes("top:1100px"));
  assert.ok(emojiMotif({ id: "g1", item: { emoji: "🐔" }, t0: 1, at: 2, t1: 4, zones: { card: 1, strip: 1500 } }).cssItem.includes("top:1500px"));
  const solo = emojiMotif({ id: "g2", item: { emoji: "🔥" }, t0: 5, at: 5.5, t1: 7.5, zones: graphicZones({ mode: "split" }) });
  assert.ok(!solo.html.includes("g2t") && solo.script.includes('y:-60') && solo.script.includes('visibility:"hidden"},7.5'));
});


test("builder: una escena de emoji compone, pasa el linter y no nombra fuentes sin @font-face", async () => {
  const dir = tmp();
  const video = makeVideo(join(dir, "src.mp4"), 12);
  const request = parseRequest({
    video: "a.mp4", output: "b.mp4", duration: 12,
    graphics: [kw({ at: 3, text: "Vótame gallina" }), { type: "emoji", at: 6, lead: 0.8, emoji: "🐔", target: "🗳️" }, { type: "emoji", at: 9, emoji: "🔥" }],
  });
  const work = join(dir, "work");
  buildProject({ request, video, workDir: work });
  const html = readFileSync(join(work, "index.html"), "utf8");
  assert.ok(html.includes("🐔") && html.includes("🗳️") && html.includes("🔥") && !/Noto Color Emoji|Apple Color Emoji|Segoe UI Emoji/.test(html));
  assert.equal((await checkProject(work)).totalErrors, 0);
});


test("zonas de los gráficos: fijas en split; en full cuelgan de la parte nítida y no pasan del 15 % inferior de Shorts", () => {
  assert.deepEqual(graphicZones({ mode: "split", top_ratio: 0.5 }), { card: 1290, strip: 1100 });
  assert.deepEqual(graphicZones({ mode: "full", top_ratio: 0.66 }), { card: 1336, strip: 1351 });
  const low = graphicZones({ mode: "full", top_ratio: 0.9 });
  assert.ok(low.card + 230 <= 1632 && low.strip + 200 <= 1632);
  const request = parseRequest({ ...base, layout: { mode: "full", top_ratio: 0.66 }, graphics: [kw({ at: 5 })] });
  assert.equal(request.layout.mode, "full");
  const out = graphicsLayer({ items: request.graphics, map: makeTimeMap(undefined), clipDuration: 20, zones: graphicZones(request.layout) });
  assert.ok(out.css.includes("#g0{top:1336px}"));
});


import { breakScript, tilesHtml, vaporizeScript } from "../src/motifs/dissolve.mjs";
import { imageBox, imageInner, imageMotif } from "../src/motifs/image.mjs";

const IMG = { id: "g3", item: { image: "u1/assets/7.png" }, t0: 5, at: 5.5, t1: 8, zones: { card: 1290, strip: 1100 }, files: { "u1/assets/7.png": "gfx_img0.png" } };

test("contrato de image: ruta png, estilo y efecto con valores por defecto y validados", () => {
  const ok = parseRequest({ ...base, graphics: [{ type: "image", at: 6, image: "u1/assets/7.png" }] }).graphics[0];
  assert.deepEqual([ok.style, ok.effect, ok.lead, ok.duration], ["original", "pop", 0.5, 2.5]);
  const e = parseRequest({ ...base, graphics: [{ type: "image", at: 6, image: "u1/assets/7.png", style: "card", effect: "vaporize" }] }).graphics[0];
  assert.deepEqual([e.style, e.effect], ["card", "vaporize"]);
  for (const bad of [{ image: "../x.png" }, { image: "u1/a.jpg" }, { image: "u1/a.png", style: "otro" }, { image: "u1/a.png", effect: "explotar" }, {}])
    assert.throws(() => parseRequest({ ...base, graphics: [{ type: "image", at: 6, ...bad }] }), ContractError, JSON.stringify(bad));
  assert.equal(parseRequest({ ...base, graphics: [{ type: "emoji", at: 6, emoji: "🐷", effect: "vaporize" }] }).graphics[0].effect, "vaporize");
  assert.throws(() => parseRequest({ ...base, graphics: [{ type: "emoji", at: 6, emoji: "🐷", effect: "break" }] }), ContractError);
});

test("teselas: una rejilla completa, cada una con su copia del contenido desplazada", () => {
  const html = tilesHtml({ id: "g0", inner: "<b>x</b>", w: 300, h: 300, cols: 10, rows: 10 });
  assert.equal((html.match(/class="vt"/g) ?? []).length, 100);
  assert.ok(html.includes('id="g0v0"') && html.includes('id="g0v99"') && html.includes("left:-270px;top:-270px"));
});

test("vaporizar: determinista, onda de izquierda a derecha y nada empieza antes de la palabra", () => {
  const a = vaporizeScript({ id: "g0", cols: 10, rows: 10, at: 5.5, seed: 3 });
  assert.equal(a, vaporizeScript({ id: "g0", cols: 10, rows: 10, at: 5.5, seed: 3 }));
  assert.notEqual(a, vaporizeScript({ id: "g0", cols: 10, rows: 10, at: 5.5, seed: 4 }));
  const starts = [...a.matchAll(/ease:"power2.in"\},([\d.]+)\);/g)].map((m) => Number(m[1]));
  assert.equal(starts.length, 100);
  assert.ok(Math.min(...starts) >= 5.5 && Math.max(...starts) <= 5.5 + 0.6 + 1e-9);
  assert.ok(!/NaN|undefined/.test(a));
});

test("partir: dos mitades que giran ±9° y se separan 34 px, con chispas", () => {
  const s = breakScript({ id: "g1", w: 300, h: 300, at: 4, seed: 2 });
  assert.ok(s.includes('rotation:-9,x:-34,duration:0.45') && s.includes('rotation:9,x:34,duration:0.45'));
  assert.equal((s.match(/#g1s\d+",\{x:0,y:0,opacity:1\}/g) ?? []).length, 9);
});

test("image: estilos, efectos y posición dentro de la zona de Shorts", () => {
  assert.deepEqual(imageBox("original"), { w: 300, h: 300 });
  assert.deepEqual(imageBox("card"), { w: 340, h: 380 });
  assert.ok(imageInner("original", "a.png", imageBox("original")).includes('<img class="imo" src="a.png"'));
  assert.ok(imageInner("red", "a.png", imageBox("red")).includes("#DA2E09") && imageInner("silhouette", "a.png", imageBox("silhouette")).includes("#1D1A17"));
  const card = imageMotif({ ...IMG, item: { ...IMG.item, style: "card", effect: "pop" } });
  assert.ok(card.html.includes("gfx_img0.png") && card.script.includes("rotation:-5") && card.cssItem.includes("top:1252px"), card.cssItem);   // 1632 − 380
  const vap = imageMotif({ ...IMG, item: { ...IMG.item, effect: "vaporize" } });
  assert.equal((vap.html.match(/class="vt"/g) ?? []).length, 100);
  assert.deepEqual(vap.sfx, [{ kind: "pop", at: 5 }, { kind: "dust", at: 5.5 }]);
  const brk = imageMotif({ ...IMG, item: { ...IMG.item, effect: "break" } });
  assert.ok(brk.html.includes('id="g3L"') && brk.html.includes('id="g3R"') && brk.html.includes('id="g3s8"'));
  assert.deepEqual(brk.sfx, [{ kind: "pop", at: 5 }, { kind: "crack", at: 5.5 }]);
  assert.deepEqual(imageMotif(IMG).sfx, [{ kind: "pop", at: 5 }]);
});

test("emoji vaporizado: teselas en la franja y polvo en la palabra; con objetivo el efecto no se aplica", () => {
  const v = emojiMotif({ id: "g4", item: { emoji: "🐷", effect: "vaporize" }, t0: 3, at: 3.5, t1: 6, zones: { card: 1, strip: 1400 } });
  assert.equal((v.html.match(/class="vt"/g) ?? []).length, 64);
  assert.ok(v.cssItem.includes("top:1400px") && v.sfx.some((s) => s.kind === "dust" && s.at === 3.5));
  const t = emojiMotif({ id: "g5", item: { emoji: "🐔", target: "🗳️", effect: "vaporize" }, t0: 3, at: 3.5, t1: 6, zones: { card: 1, strip: 1400 } });
  assert.ok(!t.html.includes("vt"));
});

test("builder: imagen en la composición con su fichero copiado, sonidos por tipo y linter limpio (vaporizar, partir y estilos)", async () => {
  const dir = tmp();
  const video = makeVideo(join(dir, "src.mp4"), 12);
  const asset = join(dir, "hucha.png");
  writeFileSync(asset, Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64"));
  const rel = "u1/assets/7.png";
  const request = parseRequest({
    video: "a.mp4", output: "b.mp4", duration: 12,
    graphics: [
      { type: "image", at: 3, image: rel, style: "card", effect: "vaporize" },
      { type: "image", at: 7, image: rel, style: "red", effect: "break" },
      { type: "emoji", at: 10, emoji: "🐷", effect: "vaporize" },
    ],
  });
  const work = join(dir, "work");
  buildProject({ request, video, workDir: work, images: { [rel]: asset } });
  const html = readFileSync(join(work, "index.html"), "utf8");
  assert.ok(existsSync(join(work, "gfx_img0.png")) && html.includes("gfx_img0.png") && !html.includes(rel));
  for (const f of ["pop.wav", "dust.wav", "crack.wav"]) assert.ok(existsSync(join(work, "sfx", f)), f);
  assert.match(html, /<audio id="sfxg0_1" src="sfx\/dust.wav" data-start="3" data-duration="0.8" data-volume="0.14">/);
  assert.equal((await checkProject(work)).totalErrors, 0);
});
