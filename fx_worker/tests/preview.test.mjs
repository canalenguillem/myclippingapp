import assert from "node:assert/strict";
import { createServer } from "node:http";
import { test, after } from "node:test";
import { lintHyperframeHtml } from "@hyperframes/lint";
import { parsePreview, ContractError } from "../src/contract.mjs";
import { buildPreviewHtml, previewDuration } from "../src/preview.mjs";
import { createApp } from "../src/server.mjs";
import { tmp } from "./helpers.mjs";

const servers = [];
after(() => servers.forEach((s) => s.close()));

test("la vista previa es un HTML autocontenido: sin red, con título escapado y los tiempos del render real", async () => {
  const req = parsePreview({ cortinilla: { title: "Spain <b>Facts</b>", kicker: "k", color: "#112233" }, outro: { handle: "@micanal", text: "Parte 2" } });
  const html = buildPreviewHtml(req);
  assert.ok(!/(src|href)=["']https?:/i.test(html) && !/url\(https?:/i.test(html), "no carga nada de la red");
  assert.ok(html.includes("data:font/woff2;base64,") && html.includes("gsap") && html.includes("#112233"));
  assert.ok(!html.includes("<b>Facts") && html.includes("&lt;b&gt;Facts&lt;/b&gt;"));
  assert.equal(previewDuration(req), 1.2 + 3.6 + 1 + 2.5);
  assert.ok(html.includes(`data-duration="${previewDuration(req)}"`) && html.includes('id="cort" class="clip" data-start="1.2" data-duration="3.6"'));
  assert.ok(html.includes('id="outro" class="clip" data-start="5.8" data-duration="2.5"'));
  // gsap va en línea y el linter se queja de su Math.random()/Date.now(): solo cuentan los errores de NUESTRO código
  const lint = await lintHyperframeHtml(html);
  const own = lint.findings.filter((f) => f.severity === "error" && !String(f.snippet ?? "").startsWith("/*! * GSAP"));
  assert.deepEqual(own, []);
});

test("contrato de la vista previa: por defecto vacío es válido y se rechazan campos ajenos", () => {
  assert.ok(buildPreviewHtml(parsePreview({})).includes("TU CLIP"));
  assert.throws(() => parsePreview({ cortinilla: { at: 3 } }), ContractError);
  assert.throws(() => parsePreview({ cortinilla: { color: "rojo" } }), ContractError);
  assert.throws(() => parsePreview({ otro: 1 }), ContractError);
});

test("POST /previews devuelve html y duración; una petición mala da 400", async () => {
  const app = createApp({ mediaDir: tmp("media-"), workRoot: tmp("work-") });
  const server = createServer(app.handle);
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  servers.push(server);
  const base = `http://127.0.0.1:${server.address().port}`;
  const post = (body) => fetch(`${base}/previews`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const ok = await post({ cortinilla: { title: "A B" } });
  const body = await ok.json();
  assert.equal(ok.status, 200);
  assert.ok(body.html.startsWith("<!doctype html>") && body.duration === 8.3);
  assert.equal((await post({ cortinilla: { duration: 99 } })).status, 400);
});
