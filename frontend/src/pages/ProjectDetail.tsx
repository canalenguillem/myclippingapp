import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import ClipCard from "../components/ClipCard";
import SourcePlayer from "../components/SourcePlayer";
import SpeakerPanel from "../components/SpeakerPanel";
import TranscriptView from "../components/TranscriptView";
import type { Channel, Clip, Project, Speaker, Template, Transcript } from "../types";
import { STATUS_LABEL } from "./Projects";

const BUSY = new Set(["downloading", "transcribing"]);

export default function ProjectDetail() {
  const { id } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [clipsPerPart, setClipsPerPart] = useState(4);
  const [targetDur, setTargetDur] = useState(40);
  const [parts, setParts] = useState<number | "">("");   // vacío = automático (5 partes, menos en vídeos cortos)
  const [templates, setTemplates] = useState<Template[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [videoUrl, setVideoUrl] = useState("");
  const [now, setNow] = useState(0);
  const [follow, setFollow] = useState(true);
  const video = useRef<HTMLVideoElement>(null);
  const rangeEnd = useRef<number | null>(null);    // «Escuchar» una selección: se para al llegar al final

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

  useEffect(() => { api<Template[]>("/api/templates").then(setTemplates).catch(() => setTemplates([])); }, []);
  useEffect(() => { api<Channel[]>("/api/channels").then(setChannels).catch(() => setChannels([])); }, []);
  // Vídeo fuente (URL firmada que dura 1 h) y reloj para el karaoke: mientras suena, se lee su tiempo unas 10 veces por segundo.
  const hasTranscript = Boolean(transcript);
  useEffect(() => {
    if (!hasTranscript) return;
    const load = () => api<{ url: string }>(`/api/projects/${id}/video-url`).then((r) => setVideoUrl(r.url)).catch(() => setVideoUrl(""));
    load();
    const t = setInterval(load, 50 * 60 * 1000);
    return () => clearInterval(t);
  }, [id, hasTranscript]);
  useEffect(() => {
    const t = setInterval(() => {
      const v = video.current;
      if (!v) return;
      if (!v.paused || Math.abs(v.currentTime - now) > 0.3) setNow(v.currentTime);
      if (rangeEnd.current !== null && v.currentTime >= rangeEnd.current) { v.pause(); rangeEnd.current = null; }
    }, 100);
    return () => clearInterval(t);
  }, [now]);
  const seek = (seconds: number) => { const v = video.current; if (v) { rangeEnd.current = null; v.currentTime = Math.max(0, seconds); setNow(v.currentTime); v.play().catch(() => undefined); } };
  const listen = (start: number, end: number) => { const v = video.current; if (v) { v.currentTime = Math.max(0, start - 0.2); rangeEnd.current = end + 0.2; v.play().catch(() => undefined); } };
  const words = transcript?.words ?? [];
  const activeIndex = useMemo(() => {
    if (!words.length || !videoUrl) return null;
    let lo = 0, hi = words.length - 1, found = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (words[mid].start <= now) { found = mid; lo = mid + 1; } else hi = mid - 1; }
    return found >= 0 && now <= words[found].end + 1.2 ? found : null;   // pasado 1,2 s de silencio ya no habla nadie
  }, [words, now, videoUrl]);
  const speakerNow = activeIndex !== null ? words[activeIndex].speaker ?? null : null;

  const [handleDraft, setHandleDraft] = useState<string | null>(null);
  const saveHandle = async () => {
    if (handleDraft === null || handleDraft.trim() === (project?.source_handle ?? "")) { setHandleDraft(null); return; }
    setError("");
    try {
      setProject(await api<Project>(`/api/projects/${id}`, { method: "PATCH", json: { source_handle: handleDraft } }));
      setNotice("@ del canal original guardado; saldrá lo primero en las descripciones que generes.");
      setHandleDraft(null);
    } catch (e) { fail(e); }
  };

  const setDefaultChannel = async (value: string) => {
    setError("");
    try {
      setProject(await api<Project>(`/api/projects/${id}`, { method: "PATCH", json: { default_channel_id: value === "" ? null : Number(value) } }));
      await loadClips();   // los clips sin canal reciben el nuevo
      setNotice("Canal por defecto guardado; los clips que no tenían canal lo usan ahora.");
    } catch (e) { fail(e); }
  };
  const setDefaultTemplate = async (value: string) => {
    setError("");
    try {
      setProject(await api<Project>(`/api/projects/${id}`, { method: "PATCH", json: { default_template_id: value === "" ? null : Number(value) } }));
    } catch (e) { fail(e); }
  };

  useEffect(() => {
    loadProject();
    const t = setInterval(loadProject, 3000);
    return () => clearInterval(t);
  }, [loadProject]);

  // Mientras algún clip se renderiza o se sube (o espera en cola), la lista se refresca sola.
  const anyActive = clips.some((c) => c.render_job_id !== null || c.upload_job_id !== null || c.render_state === "rendering");
  useEffect(() => {
    if (!anyActive) return;
    const t = setInterval(loadClips, 3000);
    return () => clearInterval(t);
  }, [anyActive, loadClips]);

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
      await api(`/api/projects/${id}/detect`, { json: { clips_per_part: clipsPerPart, target_dur: targetDur, ...(parts === "" ? {} : { parts }) } });
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
      {project && (
        <label className="check">Plantilla de marca por defecto (para los clips que se detecten a partir de ahora)
          <select value={project.default_template_id == null ? "" : String(project.default_template_id)} onChange={(e) => setDefaultTemplate(e.target.value)}>
            <option value="">Sin plantilla</option>
            {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          {" "}<Link to="/templates">Editar plantillas</Link>
        </label>
      )}
      {project && (
        <label className="check">Canal de YouTube al que irán los vídeos
          <select value={project.default_channel_id == null ? "" : String(project.default_channel_id)} onChange={(e) => setDefaultChannel(e.target.value)}>
            <option value="">Sin elegir (se elige al subir cada clip)</option>
            {channels.map((c) => <option key={c.id} value={c.id}>{c.name}{c.linked ? ` — ${c.yt_title ?? "conectado"}` : " (sin conectar)"}</option>)}
          </select>
          {" "}<Link to="/channels">Editar canales</Link>
        </label>
      )}
      {project && (
        <label className="check">Canal del vídeo original (@)
          <input value={handleDraft ?? project.source_handle ?? ""} placeholder="@esRadio" maxLength={200} style={{ width: 220 }}
            onChange={(e) => setHandleDraft(e.target.value)} onBlur={saveHandle} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
          <span className="muted">Sale lo primero en la descripción de YouTube, con el enlace al vídeo original, para etiquetarlo.</span>
        </label>
      )}
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {transcript && videoUrl === "" && <p className="muted">El vídeo original se borró para liberar espacio: se descarga solo al renderizar un clip.</p>}
      {project?.error && (
        <p className="error">{project.error}{project.status === "failed" && <> <button onClick={async () => { try { await api(`/api/projects/${id}/retry`, { method: "POST" }); void loadProject(); } catch (e) { fail(e); } }}>Reintentar</button></>}</p>
      )}

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
            <label className="inline" title="El texto se reparte en partes y de cada una se piden clips (vacío: 5 partes, menos si el vídeo es corto)">partes <input type="number" min={1} max={12} placeholder="5" value={parts} onChange={(e) => setParts(e.target.value === "" ? "" : Number(e.target.value))} /></label>
            <label className="inline">clips por parte <input type="number" min={1} max={10} value={clipsPerPart} onChange={(e) => setClipsPerPart(Number(e.target.value))} /></label>
            <label className="inline">duración (s) <input type="number" min={15} max={90} value={targetDur} onChange={(e) => setTargetDur(Number(e.target.value))} /></label>
            <button onClick={detect} disabled={busy || !transcript}>{clips.length ? "Re-detectar clips" : "Detectar clips"}</button>
          </div>
        </div>
        {project?.status === "detecting" && <p className="muted">Detectando clips…</p>}
        <div className="clip-grid">
          {clips.map((c) => (
            <ClipCard key={c.id} clip={c} onApprove={() => clipAction(c, "approve")} onUnapprove={() => clipAction(c, "unapprove")} onDelete={() => deleteClip(c)} hasChannel={project?.default_channel_id != null || c.channel_id !== null}
              onAutoPublish={async (privacy) => {
                try { await api(`/api/clips/${c.id}/auto-publish`, { method: "PUT", json: { privacy } }); await loadClips(); setNotice(privacy ? "Se publicará solo al terminar el render: genera el SEO y sube el vídeo." : "Ya no se publicará solo."); }
                catch (e) { fail(e); }
              }} />
          ))}
        </div>
        {clips.length === 0 && project?.status !== "detecting" && <p className="muted">Aún no hay clips.</p>}
      </section>

      {project && Object.keys(project.speakers).length > 0 && (
        <section>
          <h2>Speakers</h2>
          <SpeakerPanel speakers={project.speakers} onSave={saveSpeakers} projectId={project.id} speakingNow={speakerNow} />
        </section>
      )}
      {transcript && project && (
        <div className={`watch-layout${videoUrl ? " with-video" : ""}`}>
          <section className="watch-main">
            <h2>Transcripción</h2>
            <TranscriptView words={transcript.words} speakers={project.speakers} busy={busy} onEditWord={editWord} onAssign={assign}
              activeIndex={activeIndex} follow={follow && !!videoUrl} onSeek={videoUrl ? seek : undefined} onListen={videoUrl ? listen : undefined} />
          </section>
          {videoUrl && (
            <aside className="watch-side">
              <SourcePlayer videoRef={video} url={videoUrl} now={now} speaker={speakerNow}
                speakerName={speakerNow ? project.speakers[speakerNow]?.name || `Speaker ${speakerNow}` : ""} labels={Object.keys(project.speakers).sort()}
                follow={follow} onFollow={setFollow} onSpeed={(r) => { if (video.current) video.current.playbackRate = r; }}
                onSeekBy={(d) => { const v = video.current; if (v) { v.currentTime = Math.max(0, v.currentTime + d); setNow(v.currentTime); } }} />
            </aside>
          )}
        </div>
      )}
    </div>
  );
}
