// Render REAL con Chrome. Se activa con FX_INTEGRATION=1 (npm run test:integration); tarda ~1 min.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { join } from "node:path";
import { after, test } from "node:test";
import { createApp } from "../../src/server.mjs";
import { makeVideo, probe, tmp } from "../helpers.mjs";

const skip = process.env.FX_INTEGRATION !== "1" && "ponga FX_INTEGRATION=1 para ejecutar el render real";
let server;
after(() => server?.close());

const psnr = (a, b, crop) => {
  const r = spawnSync("ffmpeg", ["-v", "info", "-ss", "1", "-i", a, "-ss", "1", "-i", b, "-filter_complex",
    `[0:v]crop=${crop},format=gray[x];[1:v]crop=${crop},format=gray[y];[x][y]psnr`, "-frames:v", "1", "-f", "null", "-"], { encoding: "utf8" });
  const m = r.stderr.match(/average:(\S+)/);
  return m[1] === "inf" ? 100 : Number(m[1]);
};

test("render real: 1080x1920, duración, audio y subtítulos pintados", { skip, timeout: 240000 }, async () => {
  const mediaDir = tmp("media-");
  const src = makeVideo(join(mediaDir, "u1/p1/clip.mp4"), 3);
  const app = createApp({ mediaDir, workers: 2 });
  server = createServer(app.handle);
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const post = await fetch(`${base}/renders`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ video: "u1/p1/clip.mp4", output: "u1/p1/out.mp4", duration: 3, quality: "draft",
      words: [{ text: "Hola", start: 0.5, end: 1.0 }, { text: "mundo", start: 1.1, end: 1.6 }] }),
  });
  assert.equal(post.status, 202);
  const { id } = await post.json();
  let rec;
  for (let i = 0; i < 2000; i++) {
    rec = await (await fetch(`${base}/renders/${id}`)).json();
    if (["completed", "failed", "cancelled"].includes(rec.status)) break;
    await new Promise((r) => setTimeout(r, 100));
  }
  assert.equal(rec.status, "completed", JSON.stringify(rec));
  const out = join(mediaDir, "u1/p1/out.mp4");
  const info = probe(out, "stream=codec_type,width,height,r_frame_rate:format=duration");
  const v = info.streams.find((s) => s.codec_type === "video");
  assert.deepEqual([v.width, v.height, v.r_frame_rate], [1080, 1920, "30/1"]);
  assert.ok(info.streams.some((s) => s.codec_type === "audio"), "el audio del clip se conserva");
  assert.ok(Math.abs(Number(info.format.duration) - 3) < 0.2);
  // zona de subtítulos (cerca del corte a mitad de pantalla): distinta del original; zona alta: igual
  // La recodificación en calidad borrador ya baja la PSNR de todo el fotograma; lo que importa es la diferencia.
  const inside = psnr(out, src, "1080:140:0:905");
  const outside = psnr(out, src, "1080:300:0:100");
  assert.ok(outside - inside > 8, `los subtítulos deben estar pintados: PSNR dentro ${inside} dB, fuera ${outside} dB`);
});
