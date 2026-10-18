import assert from "node:assert/strict";
import { test } from "node:test";
import { ROOM, TOOTH_MAX, TOOTH_MIN, bandGeometry, bandLayer } from "../src/layers/band.mjs";
import { fitFontSize, groupPhrases } from "../src/layers/captions.mjs";
import { hookLayer } from "../src/layers/hook.mjs";
import { sourceIntervals, treatmentLayer } from "../src/layers/treatment.mjs";
import { PRESETS, getPreset } from "../src/presets.mjs";
import { mulberry32 } from "../src/rng.mjs";

const w = (text, start, end, speaker = "A") => ({ text, start, end, speaker });

// --- frases ------------------------------------------------------------------------------------------
test("groupPhrases: máximo 4 palabras", () => {
  const g = groupPhrases([w("a", 0, 0.1), w("b", 0.15, 0.25), w("c", 0.3, 0.4), w("d", 0.45, 0.55), w("e", 0.6, 0.7)], 5);
  assert.deepEqual(g.map((x) => x.length), [4, 1]);
});

test("groupPhrases: corta tras puntuación (también coma), tras una pausa de más de 0,35 s y al cambiar de speaker", () => {
  assert.deepEqual(groupPhrases([w("Hola,", 0, 0.3), w("amigo", 0.35, 0.6)], 5).map((x) => x.length), [1, 1]);
  assert.deepEqual(groupPhrases([w("Fin.", 0, 0.3), w("Otra", 0.35, 0.6)], 5).map((x) => x.length), [1, 1]);
  assert.deepEqual(groupPhrases([w("a", 0, 0.3), w("b", 0.8, 1)], 5).map((x) => x.length), [1, 1]); // pausa de 0,5 s
  assert.deepEqual(groupPhrases([w("a", 0, 0.3), w("b", 0.4, 0.6)], 5).map((x) => x.length), [2]);  // pausa de 0,1 s
  assert.deepEqual(groupPhrases([w("a", 0, 0.3, "A"), w("b", 0.35, 0.6, "B")], 5).map((x) => x.length), [1, 1]);
});

test("groupPhrases: unas 22 letras por frase y una palabra larga se queda sola", () => {
  const g = groupPhrases([w("constitucional", 0, 0.5), w("tribunal", 0.55, 1), w("de", 1.05, 1.2)], 5);
  assert.deepEqual(g.map((x) => x.map((y) => y.text)), [["constitucional"], ["tribunal", "de"]]);
  const solo = groupPhrases([w("anticonstitucionalmente", 0, 1)], 5);
  assert.equal(solo.length, 1);
});

test("groupPhrases: descarta lo que empieza después de la duración", () => {
  assert.deepEqual(groupPhrases([w("a", 0, 0.3), w("fuera", 6, 6.3)], 5).flat().map((x) => x.text), ["a"]);
});

test("fitFontSize: reduce el tamaño de las frases largas, con mínimo de 40", () => {
  assert.equal(fitFontSize("HOLA", "sans_upper", 64), 64);
  const big = fitFontSize("A".repeat(30), "sans_upper", 64);
  assert.ok(big < 64 && 30 * 0.7 * big <= 960);
  assert.equal(fitFontSize("A".repeat(200), "sans_upper", 64), 40);
  assert.ok(fitFontSize("a".repeat(30), "serif_italic", 62) > fitFontSize("A".repeat(30), "sans_upper", 62)); // la serif cursiva es más estrecha
});

// --- banda de papel -------------------------------------------------------------------------------------
test("el rasgado es determinista: misma semilla, mismo borde; otra semilla, otro", () => {
  const a = bandGeometry({ y0: 1400, y1: 1490, seed: 7 });
  const b = bandGeometry({ y0: 1400, y1: 1490, seed: 7 });
  const c = bandGeometry({ y0: 1400, y1: 1490, seed: 8 });
  assert.deepEqual(a, b);
  assert.notDeepEqual(a.top, c.top);
  assert.equal(bandLayer({ core: { y0: 1400, y1: 1490 }, paper: "#F3EEE2" }).html, bandLayer({ core: { y0: 1400, y1: 1490 }, paper: "#F3EEE2" }).html);
});

test("la banda cubre SIEMPRE la zona protegida: el borde sobresale entre 6 y 22 px en cada columna", () => {
  for (const [y0, y1] of [[1000, 1090], [1419, 1509], [60, 150], [1700, 1860]]) {
    for (const seed of [1, 7, 42, 1234]) {
      const g = bandGeometry({ y0, y1, seed });
      assert.equal(g.top.length, 1081);
      for (let x = 0; x <= 1080; x++) {
        assert.ok(g.top[x] <= y0 - TOOTH_MIN + 1e-9 && g.top[x] >= y0 - TOOTH_MAX - 1e-9, `arriba x=${x} seed=${seed}`);
        assert.ok(g.bottom[x] >= y1 + TOOTH_MIN - 1e-9 && g.bottom[x] <= y1 + TOOTH_MAX + 1e-9, `abajo x=${x} seed=${seed}`);
      }
    }
  }
});

test("el rasgado varía de verdad (no es una línea recta)", () => {
  const g = bandGeometry({ y0: 1000, y1: 1090, seed: 7 });
  assert.ok(Math.max(...g.top) - Math.min(...g.top) > 4);
});

test("el SVG de la banda deja ROOM px por arriba y por abajo, con el polígono dentro", () => {
  const { html, svgTop, height } = bandLayer({ core: { y0: 1000, y1: 1090 }, paper: "#F3EEE2" });
  assert.equal(svgTop, 1000 - ROOM);
  assert.equal(height, 90 + 2 * ROOM);
  for (const m of html.matchAll(/(\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/g)) {
    const y = Number(m[2]);
    assert.ok(y >= 0 && y <= height, `punto fuera del svg: ${m[0]}`);
  }
});

// --- blanco y negro ---------------------------------------------------------------------------------------
test("sourceIntervals: tramos de los speakers is_source, ampliados y unidos si están a menos de 0,6 s", () => {
  const speakers = { A: { is_source: false }, B: { is_source: true } };
  const words = [w("x", 0, 1, "A"), w("a", 2, 2.4, "B"), w("b", 2.6, 3, "B"), w("c", 5, 5.5, "B"), w("y", 6, 7, "A")];
  const iv = sourceIntervals(words, speakers, 10);
  assert.equal(iv.length, 2);
  assert.deepEqual(iv[0].map((n) => +n.toFixed(2)), [1.9, 3.2]);
  assert.deepEqual(iv[1].map((n) => +n.toFixed(2)), [4.9, 5.7]);
  assert.deepEqual(sourceIntervals(words, { A: {}, B: {} }, 10), []);
});

test("treatmentLayer: sin tramos no escribe nada; con tramos entra y sale del blanco y negro", () => {
  assert.equal(treatmentLayer({ intervals: [] }).script, "");
  const { script } = treatmentLayer({ intervals: [[1, 3]] });
  assert.ok(script.includes('"#vwrap"') && script.includes('filter:"grayscale(1)"') && script.includes('filter:"grayscale(0)"'));
  assert.ok(script.includes(",1);") && script.includes(",2.8);")); // entra en 1 s y empieza a salir 0,2 s antes del final
});

// --- gancho y presets ---------------------------------------------------------------------------------------
test("gancho: la última palabra es el acento solo en el preset editorial", () => {
  const ed = hookLayer({ hook: { text: "Nadie se lo esperaba", duration: 2 }, preset: PRESETS.editorial });
  assert.ok(ed.html.includes('<span class="acc">ESPERABA</span>'));
  const hz = hookLayer({ hook: { text: "Nadie se lo esperaba", duration: 2 }, preset: PRESETS.hormozi });
  assert.ok(!hz.html.includes("acc"));
  assert.ok(ed.script.includes("blur(24px)") && ed.script.includes("visibility"));
});

test("gancho: el tamaño baja con el texto largo", () => {
  const size = (t) => Number(hookLayer({ hook: { text: t, duration: 2 }, preset: PRESETS.editorial }).css.match(/font-size:(\d+)px/)[1]);
  assert.ok(size("Corto") > size("Un titular bastante más largo que cabe") );
});

test("presets: editorial lleva banda, los otros no; uno desconocido cae en editorial", () => {
  assert.equal(PRESETS.editorial.band, true);
  assert.equal(PRESETS.hormozi.band, false);
  assert.equal(PRESETS.minimal.band, false);
  assert.equal(getPreset("nada"), PRESETS.editorial);
});

test("mulberry32 es determinista", () => {
  const a = mulberry32(5), b = mulberry32(5);
  assert.deepEqual([a(), a(), a()], [b(), b(), b()]);
});
