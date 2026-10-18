// Ejecuta el render con la API de Node de HyperFrames y mide tiempo, memoria, progreso y cancelación.
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRenderJob, executeRenderJob } from "@hyperframes/producer";
import { buildProject } from "./build.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const arg = (name, dflt) => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : dflt; };
const quality = arg("quality", "draft");
const fps = Number(arg("fps", 30));
const workers = arg("workers", undefined);
const cancelAfter = arg("cancel-after", undefined);
const outName = arg("out", `spike-${quality}.mp4`);

process.env.HYPERFRAMES_TELEMETRY = "0";
const project = join(here, "project");
const { total } = buildProject(project);
mkdirSync(join(here, "out"), { recursive: true });
const output = join(here, "out", outName);

// Memoria máxima del árbol de procesos (node + Chrome + ffmpeg), muestreada cada 400 ms.
let peakKb = 0;
const sample = () => {
  try {
    const rows = execFileSync("ps", ["-eo", "pid=,ppid=,rss="], { encoding: "utf8" }).trim().split("\n").map((l) => l.trim().split(/\s+/).map(Number));
    const kids = new Map();
    for (const [pid, ppid, rss] of rows) (kids.get(ppid) ?? kids.set(ppid, []).get(ppid)).push([pid, rss]);
    const sum = (pid) => (kids.get(pid) ?? []).reduce((a, [c, rss]) => a + rss + sum(c), 0);
    peakKb = Math.max(peakKb, sum(process.pid));
  } catch { /* ps no disponible */ }
};
const timer = setInterval(sample, 400);

const options = { fps, quality, format: "mp4" };
if (workers) options.workers = Number(workers);
const job = createRenderJob(options);
const controller = new AbortController();
if (cancelAfter) setTimeout(() => controller.abort(), Number(cancelAfter) * 1000);

const t0 = Date.now();
let lastPct = -1;
const stages = new Set();
try {
  await executeRenderJob(job, project, output, (j, message) => {
    const pct = Math.floor(j.progress);
    if (message && !stages.has(message)) { stages.add(message); console.log(`  [${((Date.now() - t0) / 1000).toFixed(1)}s] ${message}`); }
    if (pct !== lastPct && pct % 20 === 0) { lastPct = pct; console.log(`  ${pct}%`); }
  }, controller.signal);
  const secs = (Date.now() - t0) / 1000;
  clearInterval(timer);
  console.log(JSON.stringify({ ok: true, quality, fps, workers: workers ?? "auto", videoSeconds: total, renderSeconds: +secs.toFixed(1), xRealtime: +(secs / total).toFixed(2), peakRssMB: Math.round(peakKb / 1024), output }));
} catch (err) {
  clearInterval(timer);
  console.log(JSON.stringify({ ok: false, error: `${err?.name}: ${err?.message}`.slice(0, 400), afterSeconds: +((Date.now() - t0) / 1000).toFixed(1) }));
  process.exitCode = 1;
}
