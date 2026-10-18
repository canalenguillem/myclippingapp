// Contrato de POST /renders. Todas las rutas son relativas al volumen compartido (MEDIA_DIR) y los tiempos
// van en SEGUNDOS, relativos al inicio del clip vertical (t = 0).
import { z } from "zod";

/** Ruta relativa y segura: sin barra inicial, sin `..`, sin barras invertidas ni caracteres de control. */
export const isSafeRel = (value) =>
  typeof value === "string" &&
  value.length > 0 &&
  value.length <= 512 &&
  !value.startsWith("/") &&
  !value.includes("\\") &&
  !/[\u0000-\u001f]/.test(value) &&
  !value.split("/").some((part) => part === ".." || part === "" || part === ".");

const relPath = z.string().refine(isSafeRel, { message: "ruta relativa no válida" });

const word = z
  .object({
    text: z.string().min(1).max(80),
    start: z.number().min(0),
    end: z.number().min(0),
    speaker: z.string().max(8).optional(),
  })
  .strict()
  .refine((w) => w.end >= w.start, { message: "end debe ser >= start" });

const speaker = z
  .object({
    name: z.string().max(80).default(""),
    role: z.string().max(120).default(""),
    caption_style: z.enum(["sans_upper", "serif_italic"]).default("sans_upper"),
    is_source: z.boolean().default(false),
  })
  .strict();

export const renderRequest = z
  .object({
    video: relPath.refine((v) => v.endsWith(".mp4"), { message: "video debe ser .mp4" }),
    output: relPath.refine((v) => v.endsWith(".mp4"), { message: "output debe ser .mp4" }),
    quality: z.enum(["draft", "standard"]).default("standard"),
    fps: z.union([z.literal(24), z.literal(30), z.literal(60)]).default(30),
    duration: z.number().positive().max(600),
    layout: z
      .object({ mode: z.literal("split"), top_ratio: z.number().min(0.2).max(0.9).default(0.5) })
      .strict()
      .default({ mode: "split", top_ratio: 0.5 }),
    words: z.array(word).max(5000).default([]),
    speakers: z.record(z.string().regex(/^[A-Za-z0-9]{1,8}$/), speaker).default({}),
    // Filas (en px del lienzo 1080x1920) que la banda debe cubrir, p. ej. donde el vídeo de origen lleva subtítulos
    // quemados. Sin este campo la banda va centrada en el corte entre el plano corto y la escena completa.
    band: z
      .object({ y0: z.number().int().min(0).max(1919), y1: z.number().int().min(1).max(1920) })
      .strict()
      .refine((b) => b.y1 > b.y0 && b.y1 - b.y0 <= 400, { message: "band: y1 debe ser mayor que y0 y la altura, de 400 px como máximo" })
      .optional(),
    hook: z
      .object({ text: z.string().min(1).max(120), duration: z.number().min(0.5).max(6).default(2) })
      .strict()
      .optional(),
    preset: z.enum(["editorial", "hormozi", "minimal"]).default("editorial"),
  })
  .strict();

/** Valida y devuelve la petición con los valores por defecto; lanza ContractError con los detalles. */
export function parseRequest(input) {
  const result = renderRequest.safeParse(input);
  if (!result.success) {
    const details = result.error.issues.map((i) => `${i.path.join(".") || "(raíz)"}: ${i.message}`);
    throw new ContractError(details);
  }
  return result.data;
}

export class ContractError extends Error {
  constructor(details) {
    super(`petición no válida: ${details.join("; ")}`);
    this.name = "ContractError";
    this.details = details;
  }
}
