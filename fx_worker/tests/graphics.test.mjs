import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { buildProject } from "../src/builder.mjs";
import { ContractError, parseRequest } from "../src/contract.mjs";
import { graphicWindow, graphicsLayer } from "../src/layers/graphics.mjs";
import { keywordMotif, keywordSize } from "../src/motifs/keyword.mjs";
import { checkProject } from "../src/render.mjs";
import { makeTimeMap } from "../src/timemap.mjs";
import { makeVideo, tmp } from "./helpers.mjs";

const base = { video: "a.mp4", output: "b.mp4", duration: 20 };
const kw = (extra = {}) => ({ type: "keyword", at: 8, text: "Indultos", ...extra });

test("contrato: valores por defecto, texto recortado y validaciones", () => {
  const g = parseRequest({ ...base, graphics: [kw({ text: "  Indultos " })] }).graphics[0];
  assert.deepEqual(g, { type: "keyword", at: 8, lead: 0.5, duration: 2.5, text: "Indultos" });
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
  assert.deepEqual(out.sfx, [{ id: "g0", type: "keyword", at: 3.5 }, { id: "g1", type: "keyword", at: 17.1 }]);
  assert.equal(graphicsLayer({ items: [], map: makeTimeMap(undefined), clipDuration: 20 }).html, "");
});

test("keyword: texto escapado en mayúsculas, tamaño ajustado y salida antes del final", () => {
  const m = keywordMotif({ id: "g0", item: { text: "<b>Hola</b>" }, t0: 1, at: 1.5, t1: 3.5 });
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
