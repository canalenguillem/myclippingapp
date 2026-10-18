import { resolve, sep } from "node:path";

export class PathError extends Error {
  constructor(message) {
    super(message);
    this.name = "PathError";
  }
}

/** Resuelve una ruta relativa dentro de MEDIA_DIR y rechaza cualquiera que se salga de él. */
export function resolveInMedia(mediaDir, rel) {
  const root = resolve(mediaDir);
  const full = resolve(root, rel);
  if (full !== root && !full.startsWith(root + sep)) throw new PathError(`ruta fuera de MEDIA_DIR: ${rel}`);
  return full;
}
