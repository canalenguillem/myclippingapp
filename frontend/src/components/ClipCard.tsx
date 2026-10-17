import { Link } from "react-router-dom";
import type { Clip } from "../types";
import { fmtTime } from "../types";

type Props = { clip: Clip; onApprove: () => void; onUnapprove: () => void; onDelete: () => void };

export default function ClipCard({ clip, onApprove, onUnapprove, onDelete }: Props) {
  return (
    <div className={`clip-card ${clip.status}`}>
      <div className="clip-top">
        <span className="score" title="Puntuación del modelo">{clip.score}</span>
        <div className="clip-main">
          <strong>{clip.hook || clip.title}</strong>
          <div className="muted">{fmtTime(clip.start)} – {fmtTime(clip.end)} · {clip.duration.toFixed(1)} s <span className={`tag ${clip.status === "approved" ? "completed" : ""}`}>{clip.status === "approved" ? "aprobado" : clip.status}</span></div>
        </div>
      </div>
      {clip.title && clip.hook && clip.title !== clip.hook && <div className="muted">{clip.title}</div>}
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
