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

// Cortinilla de inicio: se inserta en `at` (segundos del clip, sin cortinilla) y pausa el clip `duration` segundos.
const cortinilla = z
  .object({
    at: z.number().positive(),
    duration: z.number().min(1).max(10).default(3.6),
    color: z.string().regex(/^#[0-9A-Fa-f]{6}$/).default("#DA2E09"),
    template: z.literal("pill_draw").default("pill_draw"),
    // Título (la última palabra va en serif cursiva), antetítulo en mono y objeto que orbita (imagen del volumen).
    title: z.string().max(40).default(""),
    kicker: z.string().max(60).default(""),
    orbit: relPath.refine((v) => /\.(png|jpe?g|webp)$/i.test(v), { message: "orbit debe ser png, jpg o webp" }).optional(),
  })
  .strict();

// Cortinilla final: va siempre al final y NO vuelve a destapar el clip. Termina en el color de marca.
const outro = z
  .object({
    template: z.literal("cta_subscribe").default("cta_subscribe"),
    duration: z.number().min(1).max(10).default(2.5),
    color: z.string().regex(/^#[0-9A-Fa-f]{6}$/).default("#DA2E09"),
    handle: z.string().max(40).default(""),
    text: z.string().max(80).default(""),
    like: z.string().min(1).max(20).default("ME GUSTA"),
    subscribe: z.string().min(1).max(20).default("SUSCRÍBETE"),
  })
  .strict();

// Gráficos ligados a la transcripción. `at` es el inicio de la palabra gancho (segundos del clip sin cortinillas); el gráfico
// entra `lead` s antes y vive `duration` s en total (2–4 s en la práctica; el programador del backend lo impone).
const graphicBase = { at: z.number().min(0), lead: z.number().min(0).max(1).default(0.5), duration: z.number().min(1).max(6).default(2.5) };
const emojiText = z.string().min(1).max(16).regex(/^\p{Extended_Pictographic}[\p{Extended_Pictographic}\u200d\ufe0f\u{1F3FB}-\u{1F3FF}]*$/u, "debe ser un emoji");
const graphic = z.discriminatedUnion("type", [
  z.object({ type: z.literal("emoji"), ...graphicBase, emoji: emojiText, target: emojiText.optional() }).strict(),
  z.object({ type: z.literal("keyword"), ...graphicBase, text: z.string().trim().min(1).max(40), zone: z.enum(["bottom", "top"]).default("bottom") }).strict(),
]);

export const renderRequest = z
  .object({
    video: relPath.refine((v) => v.endsWith(".mp4"), { message: "video debe ser .mp4" }),
    output: relPath.refine((v) => v.endsWith(".mp4"), { message: "output debe ser .mp4" }),
    quality: z.enum(["draft", "standard"]).default("standard"),
    fps: z.union([z.literal(24), z.literal(30), z.literal(60)]).default(30),
    duration: z.number().positive().max(600),
    layout: z
      .object({ mode: z.enum(["split", "full"]).default("split"), top_ratio: z.number().min(0.2).max(0.9).default(0.5) })
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
    cortinilla: cortinilla.optional(),
    outro: outro.optional(),
    graphics: z.array(graphic).max(60).default([]),
    sfx: z.boolean().default(true), // whoosh en cada barrido y brillo mientras se dibuja la píldora
  })
  .strict()
  .superRefine((r, ctx) => {
    r.graphics.forEach((g, i) => {
      const start = Math.max(0, g.at - g.lead);
      const end = Math.min(r.duration, start + g.duration);
      const path = ["graphics", i, "at"];
      if (g.at > r.duration) ctx.addIssue({ code: "custom", path, message: "el gráfico se ancla fuera del clip" });
      if (r.cortinilla && start < r.cortinilla.at && end > r.cortinilla.at)
        ctx.addIssue({ code: "custom", path, message: "un gráfico no puede cruzar la cortinilla de inicio" });
    });
    if (!r.cortinilla) return;
    const { at } = r.cortinilla;
    if (at > r.duration - 1) ctx.addIssue({ code: "custom", path: ["cortinilla", "at"], message: "la cortinilla no puede entrar en el último segundo del clip" });
    if (r.words.some((w) => w.start < at && w.end > at)) ctx.addIssue({ code: "custom", path: ["cortinilla", "at"], message: "la cortinilla no puede pisar una palabra" });
  });

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


/** Vista previa de una plantilla (cortinilla de inicio + final sobre un clip de relleno), sin renderizar. */
export const previewRequest = z
  .object({
    // `{}` y ausente dan los valores por defecto de cada plantilla (preprocess: `.default({})` no los aplica en zod 4)
    cortinilla: z.preprocess((v) => v ?? {}, cortinilla.omit({ at: true, orbit: true })),
    outro: z.preprocess((v) => v ?? {}, outro),
  })
  .strict();

export function parsePreview(input) {
  const result = previewRequest.safeParse(input);
  if (!result.success) throw new ContractError(result.error.issues.map((i) => `${i.path.join(".") || "(raíz)"}: ${i.message}`));
  return result.data;
}
