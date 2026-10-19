import assert from "node:assert/strict";
import { existsSync, readdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { join } from "node:path";
import { after, test } from "node:test";
import { createApp } from "../src/server.mjs";
import { tmp, touch } from "./helpers.mjs";

const servers = [];
after(() => servers.forEach((s) => s.close()));

async function start(renderer, extra = {}) {
  const mediaDir = tmp("media-");
  touch(join(mediaDir, "u1/p1/clip.mp4"));
  const app = createApp({ mediaDir, renderer, workRoot: tmp("work-"), ...extra });
  const server = createServer(app.handle);
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  servers.push(server);
  const base = `http://127.0.0.1:${server.address().port}`;
  const call = async (method, path, body) => {
    const res = await fetch(base + path, { method, body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body), headers: { "content-type": "application/json" } });
    return { status: res.status, body: await res.json() };
  };
  const waitFor = async (id, pred, ms = 3000) => {
    const t0 = Date.now();
    for (;;) {
      const r = await call("GET", `/renders/${id}`);
      if (pred(r.body)) return r.body;
      if (Date.now() - t0 > ms) throw new Error(`timeout: ${JSON.stringify(r.body)}`);
      await new Promise((x) => setTimeout(x, 10));
    }
  };
  return { call, waitFor, mediaDir, app };
}

const valid = { video: "u1/p1/clip.mp4", output: "u1/p1/draft.mp4", duration: 3, quality: "draft" };
const okRenderer = async ({ outputPath, onProgress }) => {
  onProgress(40, "capturando");
  writeFileSync(outputPath, "mp4");
  return { seconds: 1.5 };
};

test("health", async () => {
  const { call } = await start(okRenderer);
  const r = await call("GET", "/health");
  assert.deepEqual(r.body, { ok: true, engine: "hyperframes", busy: false });
});

test("un render válido se completa, deja el MP4 en su sitio y limpia lo temporal", async () => {
  const seen = {};
  const { call, waitFor, mediaDir } = await start(async (o) => {
    seen.dir = o.projectDir;
    seen.workers = o.workers;
    seen.fps = o.fps;
    assert.ok(existsSync(join(o.projectDir, "index.html")));
    return okRenderer(o);
  }, { workers: 3 });
  const r = await call("POST", "/renders", valid);
  assert.equal(r.status, 202);
  const rec = await waitFor(r.body.id, (b) => b.status === "completed");
  assert.equal(rec.progress, 100);
  assert.equal(rec.output, "u1/p1/draft.mp4");
  assert.ok(existsSync(join(mediaDir, "u1/p1/draft.mp4")));
  assert.deepEqual(readdirSync(join(mediaDir, "u1/p1")).sort(), ["clip.mp4", "draft.mp4"]); // sin .part
  assert.ok(!existsSync(seen.dir), "el directorio de trabajo se borra");
  assert.deepEqual([seen.workers, seen.fps], [3, 30]);
});

test("peticiones no válidas", async () => {
  const { call } = await start(okRenderer);
  let r = await call("POST", "/renders", { ...valid, duration: -1 });
  assert.equal(r.status, 400);
  assert.equal(r.body.error, "invalid_request");
  assert.ok(r.body.details.some((d) => d.startsWith("duration")));
  r = await call("POST", "/renders", { ...valid, video: "../etc/passwd.mp4" });
  assert.equal(r.status, 400);
  r = await call("POST", "/renders", { ...valid, video: "u1/p1/no_existe.mp4" });
  assert.deepEqual([r.status, r.body.error], [422, "video_not_found"]);
  r = await call("POST", "/renders", { ...valid, duration: 10, cortinilla: { at: 4, orbit: "u1/p1/no_existe.png" } });
  assert.deepEqual([r.status, r.body.error], [422, "orbit_not_found"]);
  r = await call("POST", "/renders", { ...valid, duration: 10, cortinilla: { at: 4, orbit: "../../etc/x.png" } });
  assert.equal(r.status, 400);
  r = await call("POST", "/renders", "esto no es json");
  assert.equal(r.status, 400);
  r = await call("POST", "/renders", { ...valid, words: Array.from({ length: 100000 }, () => ({ text: "a", start: 0, end: 1 })) });
  assert.equal(r.status, 413);
  r = await call("GET", "/nada");
  assert.equal(r.status, 404);
  r = await call("GET", "/renders/no-es-un-uuid");
  assert.equal(r.status, 404);
  r = await call("GET", "/renders/00000000-0000-0000-0000-000000000000");
  assert.equal(r.status, 404);
});

test("solo atiende un render a la vez", async () => {
  let release;
  const gate = new Promise((r) => (release = r));
  const { call, waitFor } = await start(async (o) => {
    await gate;
    return okRenderer(o);
  });
  const first = await call("POST", "/renders", valid);
  assert.equal(first.status, 202);
  const second = await call("POST", "/renders", { ...valid, output: "u1/p1/otro.mp4" });
  assert.deepEqual([second.status, second.body.error], [409, "busy"]);
  assert.equal((await call("GET", "/health")).body.busy, true);
  release();
  await waitFor(first.body.id, (b) => b.status === "completed");
  assert.equal((await call("POST", "/renders", { ...valid, output: "u1/p1/otro.mp4" })).status, 202);
});

test("cancelar aborta el render, no deja ficheros y libera el servicio", async () => {
  let signal;
  const { call, waitFor, mediaDir } = await start(async (o) => {
    signal = o.signal;
    writeFileSync(o.outputPath, "a medias");
    await new Promise((_, reject) => o.signal.addEventListener("abort", () => reject(Object.assign(new Error("render_cancelled"), { name: "RenderCancelledError" }))));
  });
  const { body } = await call("POST", "/renders", valid);
  await waitFor(body.id, (b) => b.status === "running");
  const del = await call("DELETE", `/renders/${body.id}`);
  assert.equal(del.status, 202);
  const rec = await waitFor(body.id, (b) => b.status === "cancelled");
  assert.equal(rec.error, null);
  assert.ok(signal.aborted);
  assert.deepEqual(readdirSync(join(mediaDir, "u1/p1")), ["clip.mp4"]);
  assert.equal((await call("DELETE", `/renders/${body.id}`)).status, 409); // ya terminado
  assert.equal((await call("POST", "/renders", valid)).status, 202);
});

test("un fallo del renderizador queda registrado y no bloquea el siguiente", async () => {
  let calls = 0;
  const { call, waitFor, mediaDir } = await start(async (o) => {
    if (calls++ === 0) {
      writeFileSync(o.outputPath, "x");
      throw new Error("Chrome se cayó");
    }
    return okRenderer(o);
  });
  const a = await call("POST", "/renders", valid);
  const rec = await waitFor(a.body.id, (b) => b.status === "failed");
  assert.match(rec.error, /Chrome se cayó/);
  assert.deepEqual(readdirSync(join(mediaDir, "u1/p1")), ["clip.mp4"]);
  const b = await call("POST", "/renders", valid);
  assert.equal(b.status, 202);
  await waitFor(b.body.id, (x) => x.status === "completed");
});

test("un render que no genera fichero falla en vez de dar por bueno uno vacío", async () => {
  const { call, waitFor } = await start(async () => ({ seconds: 0 }));
  const { body } = await call("POST", "/renders", valid);
  const rec = await waitFor(body.id, (b) => b.status === "failed");
  assert.match(rec.error, /no generó/);
});

test("los registros terminados caducan", async () => {
  let t = 1000;
  const { call, waitFor, app } = await start(okRenderer, { now: () => t });
  const { body } = await call("POST", "/renders", valid);
  await waitFor(body.id, (b) => b.status === "completed");
  app.sweep();
  assert.equal((await call("GET", `/renders/${body.id}`)).status, 200);
  t += 61 * 60 * 1000;
  app.sweep();
  assert.equal((await call("GET", `/renders/${body.id}`)).status, 404);
});


test("con FX_MAX_RENDERS=2 admite dos renders a la vez y rechaza el tercero", async () => {
  let release;
  const gate = new Promise((r) => (release = r));
  const { call, waitFor } = await start(async (o) => {
    await gate;
    return okRenderer(o);
  }, { maxRenders: 2 });
  const a = await call("POST", "/renders", valid);
  const b = await call("POST", "/renders", { ...valid, output: "u1/p1/b.mp4" });
  const c = await call("POST", "/renders", { ...valid, output: "u1/p1/c.mp4" });
  assert.deepEqual([a.status, b.status, c.status, c.body.error], [202, 202, 409, "busy"]);
  assert.equal((await call("GET", "/health")).body.busy, true);
  release();
  await waitFor(a.body.id, (x) => x.status === "completed");
  await waitFor(b.body.id, (x) => x.status === "completed");
  assert.equal((await call("GET", "/health")).body.busy, false);
});
