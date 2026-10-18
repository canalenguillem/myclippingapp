// Render REAL de las capas de estilo, comprobado sobre píxeles. Se activa con FX_INTEGRATION=1.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { createServer } from "node:http";
import { join } from "node:path";
import { after, test } from "node:test";
import { createApp } from "../../src/server.mjs";
import { makeRedVideo, pixels, probe, tmp } from "../helpers.mjs";

const skip = process.env.FX_INTEGRATION !== "1" && "ponga FX_INTEGRATION=1 para ejecutar el render real";
const servers = [];
after(() => servers.forEach((s) => s.close()));

async function render(mediaDir, request) {
  const app = createApp({ mediaDir, workers: 2 });
  const server = createServer(app.handle);
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  servers.push(server);
  const base = `http://127.0.0.1:${server.address().port}`;
  const post = await fetch(`${base}/renders`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(request) });
  assert.equal(post.status, 202, await post.clone().text());
  const { id } = await post.json();
  for (let i = 0; i < 3000; i++) {
    const rec = await (await fetch(`${base}/renders/${id}`)).json();
    if (rec.status === "completed") return join(mediaDir, request.output);
    if (rec.status !== "queued" && rec.status !== "running") throw new Error(JSON.stringify(rec));
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("timeout");
}

const isCream = (r, g, b) => Math.abs(r - 243) < 26 && Math.abs(g - 238) < 26 && Math.abs(b - 226) < 32;
// «Es papel» = no es vídeo: ni el rojo del clip ni el blanco puro de los subtítulos quemados (el papel tiene B < 246).
// Las fibras de la textura oscurecen el crema hasta ~(217,213,201), por eso no se compara con un color exacto.
const isPaper = (r, g, b) => r > 170 && g > 165 && b > 150 && b < 246 && r - g < 40;
const isRed = (r, g, b) => r > 150 && g < 90 && b < 80;
const isBlue = (r, g, b) => b > 150 && r < 90 && g < 110;
const isGreen = (r, g, b) => g > 120 && r < 60 && b < 60;
const isGray = (r, g, b) => Math.abs(r - g) < 30 && Math.abs(g - b) < 30;

test("la banda tapa al 100 % las filas de los subtítulos quemados (con 10 px de margen)", { skip, timeout: 240000 }, async () => {
  const mediaDir = tmp("media-");
  makeRedVideo(join(mediaDir, "u1/p1/clip.mp4"), 2, { y: 1380, h: 90 });
  const out = await render(mediaDir, { video: "u1/p1/clip.mp4", output: "u1/p1/band.mp4", duration: 2, quality: "draft", band: { y0: 1380, y1: 1470 } });
  const f = pixels(out, 1.0, { x: 0, y: 1372, w: 1080, h: 107 }); // filas 1372..1478: la zona protegida con su margen
  const bad = f.count((r, g, b) => !isPaper(r, g, b));
  assert.ok(bad <= 5, `${bad} píxeles de la zona protegida dejan ver el vídeo o los subtítulos quemados (deben ser 0)`);
  const sample = pixels(out, 1.0, { x: 0, y: 1380, w: 1080, h: 91 });
  for (const x of [0, 1, 100, 540, 979, 1078, 1079]) {
    for (const y of [0, 45, 90]) assert.ok(isPaper(...sample.at(x, y)), `papel en (${x}, ${1380 + y}): ${sample.at(x, y)}`);
  }
  assert.ok(isRed(...pixels(out, 1.0, { x: 540, y: 1200, w: 1, h: 1 }).at(0, 0)), "fuera de la banda se sigue viendo el vídeo");
  assert.ok(isRed(...pixels(out, 1.0, { x: 540, y: 1700, w: 1, h: 1 }).at(0, 0)));
});

test("blanco y negro del clip citado, subtítulos, gancho y banda en color", { skip, timeout: 240000 }, async () => {
  const mediaDir = tmp("media-");
  makeRedVideo(join(mediaDir, "u1/p1/clip.mp4"), 4);
  const out = await render(mediaDir, {
    video: "u1/p1/clip.mp4", output: "u1/p1/style.mp4", duration: 4, quality: "draft",
    words: [
      { text: "Hola", start: 0.3, end: 0.7, speaker: "A" }, { text: "mundo", start: 0.8, end: 1.2, speaker: "A" },
      { text: "cita", start: 2.0, end: 2.4, speaker: "B" }, { text: "textual", start: 2.5, end: 3.0, speaker: "B" },
    ],
    speakers: { A: { caption_style: "sans_upper" }, B: { caption_style: "serif_italic", is_source: true } },
    hook: { text: "Nadie se lo esperaba", duration: 1.5 },
  });
  const px = (t, x, y) => pixels(out, t, { x, y, w: 1, h: 1 }).at(0, 0);
  // vídeo: a color con el speaker A, en blanco y negro con el clip citado y otra vez a color después
  assert.ok(isRed(...px(1.0, 540, 400)), `a color con el speaker A: ${px(1.0, 540, 400)}`);
  assert.ok(isGray(...px(2.5, 540, 400)), `en blanco y negro con el clip citado: ${px(2.5, 540, 400)}`);
  assert.ok(isRed(...px(3.9, 540, 400)), `vuelve a color: ${px(3.9, 540, 400)}`);
  // la banda NO se vuelve gris: sigue siendo papel crema
  const band = px(2.5, 20, 960);
  assert.ok(isCream(...band), `la banda sigue en color con el clip en B/N: ${band}`);
  // subtítulos: tinta oscura y la palabra activa en rojo de acento, sobre la banda
  const caps = pixels(out, 1.0, { x: 0, y: 915, w: 1080, h: 90 });
  assert.ok(caps.count((r, g, b) => r < 90 && g < 90 && b < 90) >= 200, "texto de tinta sobre la banda");
  assert.ok(caps.count((r, g, b) => r > 190 && g < 80 && b < 60) >= 40, "palabra activa en rojo de acento");
  // gancho: texto claro arriba durante su duración y nada después
  const hookZone = (t) => pixels(out, t, { x: 80, y: 130, w: 920, h: 300 }).count((r, g, b) => r > 235 && g > 235 && b > 235);
  assert.ok(hookZone(1.0) >= 300, "gancho visible");
  assert.ok(hookZone(3.0) < 40, "gancho desaparece");
});


test("cortinilla de inicio: pausa el clip, tapa todo con el color de marca y reanuda", { skip, timeout: 240000 }, async () => {
  const mediaDir = tmp("media-");
  const src = join(mediaDir, "u1/p1/clip.mp4");
  mkdirSync(join(src, ".."), { recursive: true });
  // 2 s rojo + 2 s azul con audio: el rojo es el tramo 1 y el azul el 2 (la cortinilla entra en el segundo 2)
  const r = spawnSync("ffmpeg", ["-y", "-v", "error",
    "-f", "lavfi", "-i", "color=c=0xC03020:s=1080x1920:r=30:d=2", "-f", "lavfi", "-i", "color=c=0x2040C0:s=1080x1920:r=30:d=2",
    "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
    "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "30", "-keyint_min", "30", "-c:a", "aac", "-shortest", src]);
  assert.equal(r.status, 0, String(r.stderr));
  const out = await render(mediaDir, {
    video: "u1/p1/clip.mp4", output: "u1/p1/cort.mp4", duration: 4, quality: "draft",
    cortinilla: { at: 2, duration: 3.6, color: "#00AA00" },
    words: [{ text: "antes", start: 0.5, end: 1.0 }, { text: "despues", start: 2.6, end: 3.2 }],
  });
  const info = probe(out, "stream=codec_type:format=duration");
  assert.ok(Math.abs(Number(info.format.duration) - 7.6) < 0.2, `duración ${info.format.duration}`);
  const px = (t, x, y) => pixels(out, t, { x, y, w: 1, h: 1 }).at(0, 0);
  assert.ok(isRed(...px(1.0, 540, 400)), `tramo 1 en rojo: ${px(1.0, 540, 400)}`);
  assert.ok(isBlue(...px(7.0, 540, 400)), `tramo 2 en azul tras la cortinilla: ${px(7.0, 540, 400)}`);
  // en pleno color de marca (entre los barridos): ni un píxel del clip en todo el fotograma
  const mid = pixels(out, 3.8, {});
  const leaked = mid.count((r, g, b) => isRed(r, g, b) || isBlue(r, g, b));
  assert.equal(leaked, 0, `${leaked} píxeles del clip asoman bajo la cortinilla`);
  assert.ok(isGreen(...px(3.8, 540, 960)) && isGreen(...px(3.8, 5, 5)) && isGreen(...px(3.8, 1075, 1915)), "color de marca a pantalla completa");
  // subtítulos: la palabra de después de la cortinilla aparece a los 2,6 + 3,6 = 6,2 s, no antes
  const ink = (t) => pixels(out, t, { x: 0, y: 915, w: 1080, h: 90 }).count((r, g, b) => (r < 90 && g < 90 && b < 90) || isRed(r, g, b)); // tinta o palabra activa en rojo
  assert.ok(ink(6.4) >= 150, "«despues» se pinta tras la cortinilla");
  assert.equal(ink(3.8), 0, "ningún subtítulo bajo la cortinilla");
});


test("cortinilla pill_draw: título blanco, píldora dibujada y antetítulo sobre el color de marca", { skip, timeout: 240000 }, async () => {
  const mediaDir = tmp("media-");
  makeRedVideo(join(mediaDir, "u1/p1/clip.mp4"), 6);
  const out = await render(mediaDir, {
    video: "u1/p1/clip.mp4", output: "u1/p1/pill.mp4", duration: 6, quality: "draft",
    cortinilla: { at: 2, duration: 3.6, color: "#2040C0", title: "Spain Facts", kicker: "España en datos" },
  });
  const white = (t, region) => pixels(out, t, region).count((r, g, b) => r > 247 && g > 247 && b > 247); // blanco puro: el crema de la banda no cuenta
  const titleZone = { x: 150, y: 900, w: 780, h: 120 };
  const pillTop = { x: 140, y: 804, w: 800, h: 12 };   // lado superior de la píldora (y = 810)
  const kickerZone = { x: 200, y: 1150, w: 680, h: 60 };
  // la banda de papel (fuera de la cortinilla) tiene fibras casi blancas: se compara con el fotograma de antes
  const base = { title: white(1.5, titleZone), pill: white(1.5, pillTop), kicker: white(1.5, kickerZone) };
  assert.ok(white(3.3, titleZone) - base.title >= 300, "título visible");
  assert.ok(white(3.3, pillTop) - base.pill >= 20, "la línea de la píldora ya dibuja el lado superior");
  assert.ok(white(3.9, kickerZone) - base.kicker >= 40, "antetítulo visible");
  assert.ok(white(3.9, pillTop) - base.pill >= 100, "la píldora está dibujada a la mitad de la cortinilla");
  assert.ok(white(5.5, titleZone) - base.title <= 60, "tras la cortinilla no queda nada");
});
