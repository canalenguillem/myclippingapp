// Servicio de render: recibe un JSON, renderiza con HyperFrames y deja el MP4 en el volumen compartido.
// Solo atiende UN render a la vez (el backend ya aplica el carril global; esto es el cinturón y los tirantes).
// Es un servicio interno de la red de Docker: no tiene autenticación y no se publica al exterior.
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, renameSync, rmSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildProject } from "./builder.mjs";
import { ContractError, parsePreview, parseRequest } from "./contract.mjs";
import { PathError, resolveInMedia } from "./paths.mjs";
import { buildPreviewHtml, previewDuration } from "./preview.mjs";
import { renderProject } from "./render.mjs";

const MAX_BODY = 2 * 1024 * 1024;
const RECORD_TTL_MS = 60 * 60 * 1000;

export function createApp({ mediaDir, workers = 2, maxRenders = 1, renderer = renderProject, workRoot = tmpdir(), now = Date.now } = {}) {
  /** @type {Map<string, any>} */
  const records = new Map();
  const controllers = new Map();

  // «ocupado» = ya hay `maxRenders` renders en cola o en marcha (el backend decide cuántos lanza a la vez; esto es el tope de seguridad)
  const busy = () => [...records.values()].filter((r) => r.status === "queued" || r.status === "running").length >= maxRenders;

  async function run(record, request, videoAbs, outputAbs, orbitAbs, images) {
    const controller = controllers.get(record.id);
    const workDir = mkdtempSync(join(workRoot, "fx-"));
    try {
      record.status = "running";
      record.startedAt = now();
      const project = buildProject({ request, video: videoAbs, workDir, orbit: orbitAbs, images });
      mkdirSync(dirname(outputAbs), { recursive: true });
      const part = outputAbs.replace(/\.mp4$/, ".part.mp4");
      const result = await renderer({
        projectDir: project.projectDir,
        outputPath: part,
        fps: request.fps,
        quality: request.quality,
        workers,
        signal: controller.signal,
        onProgress: (pct, message) => {
          record.progress = pct;
          record.message = message;
        },
      });
      if (controller.signal.aborted) throw Object.assign(new Error("render_cancelled"), { name: "RenderCancelledError" });
      if (!existsSync(part) || statSync(part).size === 0) throw new Error("el render no generó ningún fichero");
      renameSync(part, outputAbs);
      record.status = "completed";
      record.progress = 100;
      record.seconds = result?.seconds ?? null;
    } catch (err) {
      rmSync(outputAbs.replace(/\.mp4$/, ".part.mp4"), { force: true });
      if (controller.signal.aborted || err?.name === "RenderCancelledError") record.status = "cancelled";
      else {
        record.status = "failed";
        record.error = `${err?.name ?? "Error"}: ${err?.message ?? err}`.slice(0, 800);
      }
    } finally {
      record.finishedAt = now();
      controllers.delete(record.id);
      rmSync(workDir, { recursive: true, force: true });
    }
  }

  const send = (res, status, body) => {
    const data = JSON.stringify(body);
    res.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(data) });
    res.end(data);
  };

  const readJson = (req) =>
    new Promise((resolve, reject) => {
      const chunks = [];
      let size = 0;
      let tooBig = false;
      req.on("data", (c) => {
        size += c.length;
        if (tooBig) return; // se sigue leyendo y se descarta: cortar la conexión impediría al cliente recibir el 413
        if (size > MAX_BODY) {
          tooBig = true;
          chunks.length = 0;
          reject(Object.assign(new Error("cuerpo demasiado grande"), { status: 413 }));
        } else chunks.push(c);
      });
      req.on("end", () => {
        try {
          resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "null"));
        } catch {
          reject(Object.assign(new Error("JSON no válido"), { status: 400 }));
        }
      });
      req.on("error", reject);
    });

  async function handle(req, res) {
    const url = new URL(req.url, "http://x");
    const path = url.pathname;
    try {
      if (req.method === "GET" && path === "/health") return send(res, 200, { ok: true, engine: "hyperframes", busy: busy() });

      if (req.method === "POST" && path === "/previews") {
        const request = parsePreview(await readJson(req));
        return send(res, 200, { html: buildPreviewHtml(request), duration: previewDuration(request) });
      }

      if (req.method === "POST" && path === "/renders") {
        const request = parseRequest(await readJson(req));
        const videoAbs = resolveInMedia(mediaDir, request.video);
        const outputAbs = resolveInMedia(mediaDir, request.output);
        if (!existsSync(videoAbs)) return send(res, 422, { error: "video_not_found", video: request.video });
        const orbitAbs = request.cortinilla?.orbit ? resolveInMedia(mediaDir, request.cortinilla.orbit) : null;
        if (orbitAbs && !existsSync(orbitAbs)) return send(res, 422, { error: "orbit_not_found", orbit: request.cortinilla.orbit });
        if (busy()) return send(res, 409, { error: "busy" });
        const images = {};
        for (const g of request.graphics) {
          for (const rel of g.type === "image" ? [g.image] : g.type === "puppets" ? g.images : []) {
            if (images[rel]) continue;
            const abs = resolveInMedia(mediaDir, rel);
            if (!existsSync(abs)) return send(res, 422, { error: "image_not_found", image: rel });
            images[rel] = abs;
          }
        }
        const id = randomUUID();
        const record = { id, status: "queued", progress: 0, message: "", error: null, output: request.output, createdAt: now() };
        records.set(id, record);
        controllers.set(id, new AbortController());
        void run(record, request, videoAbs, outputAbs, orbitAbs, images);
        return send(res, 202, { id });
      }

      const match = path.match(/^\/renders\/([0-9a-f-]{36})$/);
      if (match) {
        const record = records.get(match[1]);
        if (!record) return send(res, 404, { error: "not_found" });
        if (req.method === "GET") return send(res, 200, record);
        if (req.method === "DELETE") {
          const controller = controllers.get(record.id);
          if (!controller) return send(res, 409, { error: "already_finished", status: record.status });
          controller.abort();
          return send(res, 202, { id: record.id, status: "cancelling" });
        }
      }
      return send(res, 404, { error: "not_found" });
    } catch (err) {
      if (err instanceof ContractError) return send(res, 400, { error: "invalid_request", details: err.details });
      if (err instanceof PathError) return send(res, 400, { error: "invalid_path", message: err.message });
      return send(res, err.status ?? 500, { error: err.status ? err.message : "internal_error", message: err.status ? undefined : String(err?.message ?? err) });
    }
  }

  const sweep = () => {
    for (const [id, r] of records) if (r.finishedAt && now() - r.finishedAt > RECORD_TTL_MS) records.delete(id);
  };
  return { handle, records, sweep };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.env.HYPERFRAMES_TELEMETRY = "0";
  const mediaDir = process.env.MEDIA_DIR ?? "/media";
  const app = createApp({ mediaDir, workers: Number(process.env.FX_WORKERS ?? 2), maxRenders: Math.max(1, Number(process.env.FX_MAX_RENDERS ?? 1)) });
  setInterval(app.sweep, 10 * 60 * 1000).unref();
  const port = Number(process.env.PORT ?? 3000);
  createServer(app.handle).listen(port, "0.0.0.0", () => console.log(`fx_worker escuchando en :${port} (MEDIA_DIR=${mediaDir})`));
}
