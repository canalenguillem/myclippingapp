import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const tmp = (prefix = "fxt-") => mkdtempSync(join(tmpdir(), prefix));

/** Vídeo vertical de prueba con audio, de `seconds` segundos, con fotogramas clave densos. */
export function makeVideo(path, seconds = 3) {
  mkdirSync(join(path, ".."), { recursive: true });
  const r = spawnSync("ffmpeg", [
    "-y", "-v", "error",
    "-f", "lavfi", "-i", `testsrc2=size=1080x1920:rate=30:duration=${seconds}`,
    "-f", "lavfi", "-i", `sine=frequency=440:duration=${seconds}`,
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "30", "-keyint_min", "30", "-c:a", "aac", "-shortest", path,
  ]);
  if (r.status !== 0) throw new Error(`ffmpeg: ${r.stderr}`);
  return path;
}

export const touch = (path, content = "x") => {
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, content);
  return path;
};

export const probe = (path, entries) =>
  JSON.parse(spawnSync("ffprobe", ["-v", "error", "-show_entries", entries, "-of", "json", path], { encoding: "utf8" }).stdout);

/** Vídeo vertical de color liso con una caja blanca que simula subtítulos quemados, y audio. */
export function makeRedVideo(path, seconds, box = { y: 1380, h: 90 }) {
  mkdirSync(join(path, ".."), { recursive: true });
  const r = spawnSync("ffmpeg", [
    "-y", "-v", "error",
    "-f", "lavfi", "-i", `color=c=0xC03020:s=1080x1920:r=30:d=${seconds},drawbox=x=100:y=${box.y}:w=880:h=${box.h}:color=white:t=fill`,
    "-f", "lavfi", "-i", `sine=frequency=440:duration=${seconds}`,
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "30", "-keyint_min", "30", "-c:a", "aac", "-shortest", path,
  ]);
  if (r.status !== 0) throw new Error(`ffmpeg: ${r.stderr}`);
  return path;
}

/** Píxeles RGB de un recorte de un fotograma: devuelve {w, h, at(x, y) -> [r,g,b], count(pred)}.
 *  En yuv420p ffmpeg recorta en posiciones y tamaños PARES, así que se pide el recorte par que lo contiene. */
export function pixels(path, t, { x = 0, y = 0, w = 1080, h = 1920 } = {}) {
  const x2 = x - (x % 2), y2 = y - (y % 2);
  const w2 = w + (x - x2) + ((w + (x - x2)) % 2), h2 = h + (y - y2) + ((h + (y - y2)) % 2);
  const ox = x - x2, oy = y - y2;
  const r = spawnSync("ffmpeg", ["-v", "error", "-ss", String(t), "-i", path, "-frames:v", "1", "-vf", `crop=${w2}:${h2}:${x2}:${y2}`, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], { maxBuffer: 64 * 1024 * 1024 });
  if (r.status !== 0 || r.stdout.length !== w2 * h2 * 3) throw new Error(`no se pudo leer el fotograma (${t}s): esperaba ${w2 * h2 * 3} bytes y llegaron ${r.stdout?.length}. ${r.stderr}`);
  const buf = r.stdout;
  const at = (px, py) => { const i = ((py + oy) * w2 + (px + ox)) * 3; return [buf[i], buf[i + 1], buf[i + 2]]; };
  return {
    w, h, at,
    count(pred) {
      let n = 0;
      for (let py = 0; py < h; py++) for (let px = 0; px < w; px++) { const [r, g, b] = at(px, py); if (pred(r, g, b)) n++; }
      return n;
    },
  };
}
