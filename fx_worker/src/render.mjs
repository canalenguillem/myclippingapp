// Render con la API de Node de HyperFrames: comprueba el proyecto, renderiza y devuelve el tiempo empleado.
import { createRenderJob, executeRenderJob } from "@hyperframes/producer";
import { lintProject } from "@hyperframes/lint";

export class LintError extends Error {
  constructor(findings) {
    super(`composición no válida: ${findings.map((f) => `${f.code}: ${f.message}`).join(" | ")}`.slice(0, 800));
    this.name = "LintError";
    this.findings = findings;
  }
}

/** Un error de lint puede significar, por ejemplo, un <audio> sin id, que saldría MUDO en el render. */
export async function checkProject(projectDir) {
  const result = await lintProject(projectDir);
  const errors = result.results.flatMap((r) => r.result.findings).filter((f) => f.severity === "error");
  if (errors.length) throw new LintError(errors);
  return result;
}

/**
 * @param {{projectDir:string, outputPath:string, fps:number, quality:string, workers:number,
 *          signal?:AbortSignal, onProgress?:(pct:number, message:string)=>void}} opts
 */
export async function renderProject({ projectDir, outputPath, fps, quality, workers, signal, onProgress }) {
  await checkProject(projectDir);
  const job = createRenderJob({ fps, quality, format: "mp4", workers });
  const t0 = Date.now();
  await executeRenderJob(
    job,
    projectDir,
    outputPath,
    (current, message) => onProgress?.(Math.max(0, Math.min(100, Math.floor(current.progress))), message ?? ""),
    signal,
  );
  return { seconds: (Date.now() - t0) / 1000 };
}
