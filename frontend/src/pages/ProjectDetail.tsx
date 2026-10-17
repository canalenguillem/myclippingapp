import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import ClipCard from "../components/ClipCard";
import SpeakerPanel from "../components/SpeakerPanel";
import TranscriptView from "../components/TranscriptView";
import type { Clip, Project, Speaker, Transcript } from "../types";
import { STATUS_LABEL } from "./Projects";

const BUSY = new Set(["downloading", "transcribing"]);

export default function ProjectDetail() {
  const { id } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [clipsPerPart, setClipsPerPart] = useState(5);
  const [targetDur, setTargetDur] = useState(40);

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  const loadProject = useCallback(() => api<Project>(`/api/projects/${id}`).then(setProject).catch(fail), [id]);
  const loadClips = useCallback(() => api<Clip[]>(`/api/projects/${id}/clips`).then(setClips).catch(fail), [id]);
  const loadTranscript = useCallback(
    () =>
      api<Transcript>(`/api/projects/${id}/transcript`)
        .then(setTranscript)
        .catch((e) => { if (!(e instanceof ApiError && e.status === 409)) fail(e); }), // 409 = aún sin transcripción
    [id],
  );

  useEffect(() => {
    loadProject();
    const t = setInterval(loadProject, 3000);
    return () => clearInterval(t);
  }, [loadProject]);

  // Al cambiar de estado (p. ej. detecting -> ready) se recargan transcripción y clips.
  const status = project?.status;
  useEffect(() => {
    if (!status || BUSY.has(status)) return;
    loadTranscript();
    loadClips();
  }, [status, loadTranscript, loadClips]);

  const run = async (fn: () => Promise<unknown>, okMsg = "") => {
    setError("");
    setNotice("");
    try {
      await fn();
      if (okMsg) setNotice(okMsg);
    } catch (e) {
      fail(e);
      if (e instanceof ApiError && e.status === 409) void loadTranscript(); // alguien cambió la transcripción
    }
  };

  const saveSpeakers = (s: Record<string, Speaker>) =>
    run(async () => { await api(`/api/projects/${id}/speakers`, { method: "PUT", json: s }); await loadProject(); }, "Speakers guardados");

  const editWord = (index: number, text: string) =>
    run(async () => {
      const r = await api<{ revision: number }>(`/api/projects/${id}/transcript/words`, { method: "PATCH", json: { revision: transcript!.revision, edits: [{ index, text }] } });
      setTranscript((t) => t && { ...t, revision: r.revision, words: t.words.map((w, i) => (i === index ? { ...w, text } : w)) });
      void loadClips();
    });

  const assign = (startIndex: number, endIndex: number, speaker: string) =>
    run(async () => {
      const r = await api<{ revision: number }>(`/api/projects/${id}/transcript/speakers`, { method: "PATCH", json: { revision: transcript!.revision, ranges: [{ start_index: startIndex, end_index: endIndex, speaker }] } });
      setTranscript((t) => t && { ...t, revision: r.revision, words: t.words.map((w, i) => (i >= startIndex && i <= endIndex ? { ...w, speaker } : w)) });
    });

  const detect = () =>
    run(async () => {
      await api(`/api/projects/${id}/detect`, { json: { clips_per_part: clipsPerPart, target_dur: targetDur } });
      await loadProject();
    }, "Detección encolada: los clips sin trabajar se sustituirán; los aprobados se conservan.");

  const retranscribe = () =>
    run(async () => {
      try {
        await api(`/api/projects/${id}/retranscribe`, { json: {} });
      } catch (e) {
        if (e instanceof ApiError && e.status === 409 && e.message.includes("force")) {
          if (!confirm("La transcripción tiene correcciones manuales. ¿Sobrescribirlas?")) return;
          await api(`/api/projects/${id}/retranscribe`, { json: { force: true } });
        } else throw e;
      }
      await loadProject();
    }, "Re-transcripción encolada.");

  const clipAction = (clip: Clip, action: "approve" | "unapprove") =>
    run(async () => { await api(`/api/clips/${clip.id}/${action}`, { method: "POST" }); await loadClips(); });
  const deleteClip = (clip: Clip) =>
    run(async () => { if (confirm("¿Borrar este clip?")) { await api(`/api/clips/${clip.id}`, { method: "DELETE" }); await loadClips(); } });

  const busy = !project || BUSY.has(project.status);

  return (
    <div className="page">
      <header className="bar">
        <Link to="/projects">← Proyectos</Link>
        <h1>{project?.title ?? "…"}</h1>
      </header>
      {project && (
        <p className="muted">
          {STATUS_LABEL[project.status] ?? project.status}
          {project.duration ? ` · ${(project.duration / 60).toFixed(1)} min` : ""}
          {transcript ? ` · ${transcript.words.length} palabras · ${transcript.language}` : ""}
        </p>
      )}
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {project?.error && <p className="error">{project.error}</p>}

      {transcript && !transcript.has_speakers && (
        <div className="banner">
          Esta transcripción se hizo antes de la diarización: no sabe quién habla.
          <button onClick={retranscribe} disabled={busy}>Re-transcribir con speakers</button>
        </div>
      )}

      <section>
        <div className="section-head">
          <h2>Clips</h2>
          <div className="row-inline">
            <label className="inline">por parte <input type="number" min={1} max={10} value={clipsPerPart} onChange={(e) => setClipsPerPart(Number(e.target.value))} /></label>
            <label className="inline">duración (s) <input type="number" min={15} max={90} value={targetDur} onChange={(e) => setTargetDur(Number(e.target.value))} /></label>
            <button onClick={detect} disabled={busy || !transcript}>{clips.length ? "Re-detectar clips" : "Detectar clips"}</button>
          </div>
        </div>
        {project?.status === "detecting" && <p className="muted">Detectando clips…</p>}
        <div className="clip-grid">
          {clips.map((c) => (
            <ClipCard key={c.id} clip={c} onApprove={() => clipAction(c, "approve")} onUnapprove={() => clipAction(c, "unapprove")} onDelete={() => deleteClip(c)} />
          ))}
        </div>
        {clips.length === 0 && project?.status !== "detecting" && <p className="muted">Aún no hay clips.</p>}
      </section>

      {project && Object.keys(project.speakers).length > 0 && (
        <section>
          <h2>Speakers</h2>
          <SpeakerPanel speakers={project.speakers} onSave={saveSpeakers} />
        </section>
      )}

      {transcript && project && (
        <section>
          <h2>Transcripción</h2>
          <TranscriptView words={transcript.words} speakers={project.speakers} busy={busy} onEditWord={editWord} onAssign={assign} />
        </section>
      )}
    </div>
  );
}
