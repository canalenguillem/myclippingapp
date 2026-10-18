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
