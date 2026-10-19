import type { RefObject } from "react";
import { fmtTime, speakerColor } from "../types";

type Props = {
  videoRef: RefObject<HTMLVideoElement>;
  url: string;
  now: number;
  /** Quién habla ahora (etiqueta «A», «B»…) y cómo mostrarlo. */
  speaker: string | null;
  speakerName: string;
  labels: string[];
  follow: boolean;
  onFollow: (v: boolean) => void;
  onSpeed: (v: number) => void;
  onSeekBy: (seconds: number) => void;
};

/** Vídeo fuente al lado de la transcripción: según avanza, se ilumina la palabra y se dice quién habla (karaoke). */
export default function SourcePlayer({ videoRef, url, now, speaker, speakerName, labels, follow, onFollow, onSpeed, onSeekBy }: Props) {
  return (
    <div className="source-player">
      {url ? <video ref={videoRef} src={url} controls preload="metadata" playsInline /> : <p className="muted">Preparando el vídeo…</p>}
      <div className="sp-now" style={{ borderLeftColor: speaker ? speakerColor(speaker, labels) : "var(--line)" }}>
        <span className="muted">Habla ahora</span>
        <strong style={{ color: speaker ? speakerColor(speaker, labels) : undefined }}>{speaker ? speakerName : "—"}</strong>
        <span className="ts">{fmtTime(now)}</span>
      </div>
      <div className="sp-controls">
        <button className="ghost" onClick={() => onSeekBy(-5)} title="Retroceder 5 s">−5 s</button>
        <button className="ghost" onClick={() => onSeekBy(5)} title="Avanzar 5 s">+5 s</button>
        <select defaultValue="1" onChange={(e) => onSpeed(Number(e.target.value))} title="Velocidad">
          {[0.5, 0.75, 1, 1.25, 1.5, 2].map((v) => <option key={v} value={v}>{v}×</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={follow} onChange={(e) => onFollow(e.target.checked)} /> Seguir el texto</label>
      </div>
    </div>
  );
}
