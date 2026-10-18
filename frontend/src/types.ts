export type CaptionStyle = "sans_upper" | "serif_italic";

export type Speaker = { name: string; role: string; caption_style: CaptionStyle; is_source: boolean };

export type Project = {
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
  zoom: number; top_ratio: number; intro_enabled: boolean; outro_enabled: boolean;
  status: string; created_at: string | null;
  /** Estado del render, aparte del editorial: none | rendering | draft | final | failed. */
  render_state: "none" | "rendering" | "draft" | "final" | "failed";
  has_draft: boolean; has_final: boolean; render_error: string | null;
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
