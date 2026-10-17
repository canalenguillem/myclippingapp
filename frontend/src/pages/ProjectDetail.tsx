import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { STATUS_LABEL, type Project } from "./Projects";

type Transcript = { language: string; text: string; words: { text: string; start: number; end: number }[] };

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export default function ProjectDetail() {
  const { id } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = () => api<Project>(`/api/projects/${id}`).then(setProject).catch((e) => setError(e.message));
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [id]);

  const ready = project && !["downloading", "transcribing", "failed"].includes(project.status);
  useEffect(() => {
    if (ready && !transcript) api<Transcript>(`/api/projects/${id}/transcript`).then(setTranscript).catch((e) => setError(e.message));
  }, [ready, transcript, id]);

  // Parrafos de ~12 palabras con su marca de tiempo inicial.
  const lines: { t: number; text: string }[] = [];
  transcript?.words.forEach((w, i) => {
    if (i % 12 === 0) lines.push({ t: w.start, text: w.text });
    else lines[lines.length - 1].text += ` ${w.text}`;
  });

  return (
    <div className="page">
      <header className="bar">
        <Link to="/projects">← Proyectos</Link>
        <h1>{project?.title ?? "…"}</h1>
      </header>
      {error && <p className="error">{error}</p>}
      {project && (
        <p className="muted">
          {STATUS_LABEL[project.status] ?? project.status}
          {project.duration ? ` · ${(project.duration / 60).toFixed(1)} min` : ""}
          {transcript ? ` · ${transcript.words.length} palabras · ${transcript.language}` : ""}
        </p>
      )}
      {project?.error && <p className="error">{project.error}</p>}
      {lines.length > 0 && (
        <div className="transcript">
          {lines.map((l, i) => (
            <p key={i}><span className="ts">{fmt(l.t)}</span> {l.text}</p>
          ))}
        </div>
      )}
      <p className="muted">La detección de clips llega en F4.</p>
    </div>
  );
}
