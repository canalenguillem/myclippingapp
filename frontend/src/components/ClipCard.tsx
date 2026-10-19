import { Link } from "react-router-dom";
import type { Clip } from "../types";
import { fmtTime } from "../types";

type Props = { clip: Clip; onApprove: () => void; onUnapprove: () => void; onDelete: () => void };

const STATUS_LABEL: Record<string, string> = { detected: "detectado", approved: "aprobado", uploaded: "subido" };
const PRIVACY_LABEL: Record<Clip["privacy"], string> = { private: "privado", unlisted: "no listado", public: "público" };

/** Qué está pasando con el render y la subida de este clip: en cola, en marcha, listo o con error. */
function activity(clip: Clip): { text: string; kind: "busy" | "queued" | "done" | "error" }[] {
  const out: { text: string; kind: "busy" | "queued" | "done" | "error" }[] = [];
  if (clip.upload_job_status) out.push({ text: clip.upload_job_status === "queued" ? "⏳ En cola para subir a YouTube" : "⬆ Subiendo a YouTube…", kind: clip.upload_job_status === "queued" ? "queued" : "busy" });
  if (clip.render_job_status === "queued") out.push({ text: "⏳ En cola para renderizar", kind: "queued" });
  else if (clip.render_job_status === "running" || clip.render_state === "rendering") out.push({ text: `⚙ Renderizando${clip.render_job_progress ? ` ${Math.round(clip.render_job_progress)} %` : "…"}`, kind: "busy" });
  else if (clip.render_state === "final") out.push({ text: "🎬 Final listo", kind: "done" });
  else if (clip.render_state === "draft") out.push({ text: "🎞 Borrador listo", kind: "done" });
  else if (clip.render_state === "failed") out.push({ text: "✖ El render falló", kind: "error" });
  if (clip.upload_error && !clip.upload_job_status && clip.status !== "uploaded") out.push({ text: "✖ La subida falló", kind: "error" });
  return out;
}

export default function ClipCard({ clip, onApprove, onUnapprove, onDelete }: Props) {
  const uploaded = clip.status === "uploaded";
  const acts = activity(clip);
  return (
    <div className={`clip-card ${clip.status}`}>
      <div className="clip-top">
        <span className="score" title="Puntuación del modelo">{clip.score}</span>
        <div className="clip-main">
          <strong>{clip.hook || clip.title}</strong>
          <div className="muted">{fmtTime(clip.start)} – {fmtTime(clip.end)} · {clip.duration.toFixed(1)} s <span className={`tag ${clip.status === "approved" || uploaded ? "completed" : ""}`}>{STATUS_LABEL[clip.status] ?? clip.status}</span></div>
        </div>
      </div>
      {clip.title && clip.hook && clip.title !== clip.hook && <div className="muted">{clip.title}</div>}
      {acts.length > 0 && (
        <div className="chips">{acts.map((a) => <span key={a.text} className={`chip act-${a.kind}`}>{a.text}</span>)}</div>
      )}
      {uploaded && (
        <div className="clip-uploaded">
          ✔ Subido{clip.uploaded_at ? ` el ${new Date(clip.uploaded_at + (clip.uploaded_at.endsWith("Z") ? "" : "Z")).toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" })}` : ""} · {PRIVACY_LABEL[clip.privacy]}
          {clip.youtube_video_id && <> · <a href={`https://www.youtube.com/watch?v=${clip.youtube_video_id}`} target="_blank" rel="noreferrer">Ver en YouTube</a></>}
        </div>
      )}
      {clip.emphasis.length > 0 && <div className="chips">{clip.emphasis.map((e, i) => <span className="chip" key={i}>{e.text}</span>)}</div>}
      <div className="clip-actions">
        <Link className="btn" to={`/clips/${clip.id}`}>Editar</Link>
        {clip.status === "detected" && <button onClick={onApprove}>Aprobar</button>}
        {clip.status === "approved" && <button className="ghost" onClick={onUnapprove}>Desaprobar</button>}
        <button className="ghost" onClick={onDelete}>Borrar</button>
      </div>
    </div>
  );
}
