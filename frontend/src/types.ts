export type CaptionStyle = "sans_upper" | "serif_italic";

export type Speaker = { name: string; role: string; caption_style: CaptionStyle; is_source: boolean };

export type Project = {
  default_template_id?: number | null;
  id: number; source_url: string; title: string; duration: number | null;
  status: string; error: string | null; created_at: string | null;
  speakers: Record<string, Speaker>;
};

/** Tiempos siempre en segundos (float). */
export type Word = { text: string; start: number; end: number; confidence: number; speaker?: string };

export type Transcript = { revision: number; language: string; words: Word[]; has_speakers: boolean };

export type Clip = {
  id: number; project_id: number; start: number; end: number; duration: number;
  title: string; reason: string; score: number; transcript: string; hook: string;
  emphasis: { start: number; text: string }[]; parts: string[];
  layout: "split" | "full" | "facecam"; focus: "left" | "center" | "right";
  zoom: number; top_ratio: number; intro_enabled: boolean; cortinilla_at: number | null;
  status: string; created_at: string | null;
  /** Estado del render, aparte del editorial: none | rendering | draft | final | failed. */
  render_state: "none" | "rendering" | "draft" | "final" | "failed";
  has_draft: boolean; has_final: boolean; render_error: string | null; render_job_id: number | null; template_id: number | null; graphics: Graphic[];
};

export const EDITABLE_CLIP = new Set(["detected", "approved"]);

export const fmtTime = (s: number): string => {
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return `${m}:${sec.toFixed(1).padStart(4, "0")}`;
};

const PALETTE = ["#da2e09", "#4da3ff", "#2fbf71", "#e0a526", "#b266ff", "#ff7ab8"];
export const speakerColor = (label: string | undefined, labels: string[]): string =>
  PALETTE[Math.max(0, labels.indexOf(label ?? "")) % PALETTE.length];

export type TemplateCortinilla = {
  title: string; kicker: string; color?: string; duration: number; handle: string;
  outro_text: string; outro_duration: number; like: string; subscribe: string;
};
export type Template = {
  id: number; name: string; preset: "editorial" | "hormozi" | "minimal"; colors: { primary?: string };
  sfx: boolean; cortinilla_default: boolean; cortinilla: Partial<TemplateCortinilla>; created_at: string | null;
};
export const EMPTY_CORTINILLA: TemplateCortinilla = {
  title: "", kicker: "", duration: 3.6, handle: "", outro_text: "", outro_duration: 2.5, like: "ME GUSTA", subscribe: "SUSCRÍBETE",
};

/** Gráfico ligado a la transcripción; `at` son segundos DEL CLIP (inicio de la palabra gancho). */
export type Graphic = {
  type: "keyword" | "emoji" | "image"; at: number; text?: string; emoji?: string; target?: string;
  asset_id?: number; style?: "original" | "card" | "silhouette" | "red"; effect?: "pop" | "vaporize" | "break" | "explode";
  entry?: "pop" | "punch" | "slide_left" | "slide_right" | "slide_top" | "drop";
};
export type Asset = { id: number; name: string; kind: string; tags: string[]; width: number; height: number; url: string | null; created_at: string | null };
export type GraphicsPlan = {
  duration: number; cortinilla_at: number | null; hook_seconds: number;
  beats: (Graphic & { lead: number; duration: number; start: number; end: number })[];
  dropped: { beat: Graphic; reason: string }[];
};
export type Interpreted = { entry: Graphic["entry"] | null; effect: Graphic["effect"] | null; style: Graphic["style"] | null; source: "keywords" | "llm" | "none"; understood: string };

export type Channel = {
  id: number; name: string; language: string; default_privacy: "private" | "unlisted" | "public"; seo_rules: string;
  has_secret: boolean; secret_hint: string | null; linked: boolean; yt_title: string | null; yt_thumbnail: string | null;
  yt_channel_id: string | null; linked_at: string | null; redirect_uri: string;
};
