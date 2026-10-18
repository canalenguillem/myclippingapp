import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import RenderPanel from "../components/RenderPanel";
import type { Clip, Project, Template, Transcript } from "../types";
import { EDITABLE_CLIP, fmtTime } from "../types";

type Draft = Pick<Clip, "start" | "end" | "title" | "hook" | "layout" | "focus" | "zoom" | "top_ratio" | "intro_enabled" | "cortinilla_at" | "template_id">;

const draftOf = (c: Clip): Draft => ({
  start: c.start, end: c.end, title: c.title, hook: c.hook, layout: c.layout, focus: c.focus,
  zoom: c.zoom, top_ratio: c.top_ratio, intro_enabled: c.intro_enabled, cortinilla_at: c.cortinilla_at, template_id: c.template_id,
});

type CortinillaOptions = { duration: number; intro: number; default: number | null; positions: { at: number; sentence: boolean }[] };

const round = (n: number) => Math.round(n * 100) / 100;
const CONTEXT = 15; // segundos de transcripción visibles antes y después del clip
const URL_REFRESH_MS = 50 * 60 * 1000; // la URL firmada dura 1 h

export default function ClipEditor() {
  const { id } = useParams();
  const [clip, setClip] = useState<Clip | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [t, setT] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const [loop, setLoop] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [options, setOptions] = useState<CortinillaOptions | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const video = useRef<HTMLVideoElement>(null);
  const seeked = useRef(false);

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  useEffect(() => {
    api<Clip>(`/api/clips/${id}`)
      .then(async (c) => {
        setClip(c);
        setDraft(draftOf(c));
        const [p, tr] = await Promise.all([
          api<Project>(`/api/projects/${c.project_id}`),
          api<Transcript>(`/api/projects/${c.project_id}/transcript`),
        ]);
        setProject(p);
        setTranscript(tr);
      })
      .catch(fail);
  }, [id]);

  useEffect(() => { api<Template[]>("/api/templates").then(setTemplates).catch(() => setTemplates([])); }, []);

  const projectId = clip?.project_id;
  const loadUrl = useCallback(() => {
    if (projectId === undefined) return;
    api<{ url: string }>(`/api/projects/${projectId}/video-url`).then((r) => setVideoUrl(r.url)).catch(fail);
  }, [projectId]);
  useEffect(() => {
    loadUrl();
    const timer = setInterval(loadUrl, URL_REFRESH_MS);
    return () => clearInterval(timer);
  }, [loadUrl]);

  // Posibles posiciones de la cortinilla de inicio para el recorte que se ve en el formulario (guardado o no).
  const wantOptions = Boolean(clip && draft?.intro_enabled);
  const optStart = draft?.start, optEnd = draft?.end;
  useEffect(() => {
    if (!clip || !wantOptions || optStart === undefined || optEnd === undefined || optEnd - optStart < 1) { setOptions(null); return; }
    const timer = setTimeout(() => {
      api<CortinillaOptions>(`/api/clips/${clip.id}/cortinilla-options?start=${optStart}&end=${optEnd}`).then(setOptions).catch(() => setOptions(null));
    }, 400);
    return () => clearTimeout(timer);
  }, [clip?.id, wantOptions, optStart, optEnd]);  // eslint-disable-line react-hooks/exhaustive-deps

  const editable = clip ? EDITABLE_CLIP.has(clip.status) : false;
  const dirty = clip && draft ? JSON.stringify(draft) !== JSON.stringify(draftOf(clip)) : false;
  const duration = draft ? draft.end - draft.start : 0;
  const problem = !draft ? "" : draft.end <= draft.start ? "El fin debe ser posterior al inicio"
    : duration < 5 || duration > 180 ? "La duración debe estar entre 5 y 180 s"
    : project?.duration && draft.end > project.duration + 0.05 ? "El fin está fuera del vídeo" : "";

  const set = (patch: Partial<Draft>) =>
    setDraft((d) => d && { ...d, ...patch, ...(("start" in patch || "end" in patch) && !("cortinilla_at" in patch) ? { cortinilla_at: null } : {}) });
  const seek = (s: number) => { if (video.current) video.current.currentTime = Math.max(0, s); };

  const onLoaded = () => {
    if (draft && !seeked.current) { seeked.current = true; seek(draft.start); }
  };
  const onTime = () => {
    const v = video.current;
    if (!v || !draft) return;
    setT(v.currentTime);
    if (v.currentTime >= draft.end - 0.02) {
      if (loop) v.currentTime = draft.start; else { v.pause(); v.currentTime = draft.end; }
    }
  };
  const onPlay = () => {
    const v = video.current;
    if (v && draft && (v.currentTime < draft.start - 0.1 || v.currentTime >= draft.end - 0.05)) v.currentTime = draft.start;
  };

  const words = transcript?.words ?? [];
  const visible = useMemo(() => {
    if (!draft) return [];
    const out: { i: number }[] = [];
    for (let i = 0; i < words.length; i++) {
      if (words[i].end >= draft.start - CONTEXT && words[i].start <= draft.end + CONTEXT) out.push({ i });
      else if (words[i].start > draft.end + CONTEXT) break;
    }
    return out;
  }, [words, draft?.start, draft?.end]);  // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!clip || !draft || problem) return;
    const base = draftOf(clip);
    const changes = Object.fromEntries(Object.entries(draft).filter(([k, v]) => v !== base[k as keyof Draft]));
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const c = await api<Clip>(`/api/clips/${clip.id}`, { method: "PATCH", json: changes });
      setClip(c);
      setDraft(draftOf(c));
      setNotice("Guardado");
    } catch (e) {
      fail(e);
    } finally {
      setSaving(false);
    }
  };

  const transition = async (action: "approve" | "unapprove") => {
    if (!clip) return;
    setError("");
    try {
      const c = await api<Clip>(`/api/clips/${clip.id}/${action}`, { method: "POST" });
      setClip(c);
    } catch (e) {
      fail(e);
    }
  };

  if (!clip || !draft) return <div className="page">{error ? <p className="error">{error}</p> : <p className="muted">Cargando…</p>}</div>;

  const total = project?.duration ?? Math.max(draft.end, 1);
  const pct = (s: number) => `${(Math.min(Math.max(s, 0), total) / total) * 100}%`;
  const activeIdx = visible.find(({ i }) => words[i].start <= t && t < words[i].end)?.i ?? null;

  return (
    <div className="page">
      <header className="bar">
        <Link to={`/projects/${clip.project_id}`}>← Proyecto</Link>
        <h1>{clip.hook || clip.title || `Clip ${clip.id}`}</h1>
        <span className={`tag ${clip.status === "approved" ? "completed" : ""}`}>{clip.status === "approved" ? "aprobado" : clip.status}</span>
      </header>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {!editable && <p className="muted">Un clip en estado «{clip.status}» ya no se puede editar.</p>}

      <div className="editor">
        <div className="editor-video">
          {videoUrl ? (
            <video ref={video} src={videoUrl} controls onLoadedMetadata={onLoaded} onTimeUpdate={onTime} onPlay={onPlay} />
          ) : <p className="muted">Preparando vídeo…</p>}
          <div className="timeline" onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            seek(((e.clientX - r.left) / r.width) * total);
          }}>
            <div className="tl-window" style={{ left: pct(draft.start), width: `calc(${pct(draft.end)} - ${pct(draft.start)})` }} />
            <div className="tl-head" style={{ left: pct(t) }} />
          </div>
          <div className="muted">{fmtTime(t)} / {fmtTime(total)} · clip de {fmtTime(draft.start)} a {fmtTime(draft.end)} ({duration.toFixed(1)} s)</div>
          <label className="check"><input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Repetir el clip</label>
        </div>

        <div className="editor-form">
          <div className="trim">
            <label>Inicio (s)
              <input type="number" step={0.1} min={0} disabled={!editable} value={draft.start}
                onChange={(e) => { const v = Number(e.target.value); set({ start: v }); seek(v); }} />
            </label>
            <div className="nudge">
              <button className="ghost" disabled={!editable} onClick={() => { const v = round(draft.start - 0.5); set({ start: v }); seek(v); }}>−0,5</button>
              <button className="ghost" disabled={!editable} onClick={() => { const v = round(draft.start + 0.5); set({ start: v }); seek(v); }}>+0,5</button>
              <button className="ghost" disabled={!editable} onClick={() => set({ start: round(t) })}>Aquí</button>
            </div>
            <label>Fin (s)
              <input type="number" step={0.1} min={0} disabled={!editable} value={draft.end}
                onChange={(e) => set({ end: Number(e.target.value) })} />
            </label>
            <div className="nudge">
              <button className="ghost" disabled={!editable} onClick={() => set({ end: round(draft.end - 0.5) })}>−0,5</button>
              <button className="ghost" disabled={!editable} onClick={() => set({ end: round(draft.end + 0.5) })}>+0,5</button>
              <button className="ghost" disabled={!editable} onClick={() => set({ end: round(t) })}>Aquí</button>
            </div>
          </div>
          {problem && <p className="error">{problem}</p>}

          <label>Gancho (máx. 6 palabras)
            <input value={draft.hook} maxLength={255} disabled={!editable} onChange={(e) => set({ hook: e.target.value })} />
          </label>
          <label>Título
            <input value={draft.title} maxLength={255} disabled={!editable} onChange={(e) => set({ title: e.target.value })} />
          </label>
          <div className="grid2">
            <label>Diseño
              <select value={draft.layout} disabled={!editable} onChange={(e) => {
                const layout = e.target.value as Draft["layout"];
                // al pasar a pantalla completa la parte nítida ocupa más (deja sitio a los gráficos abajo); al volver, el corte al medio
                const ratio = layout === "full" && draft.top_ratio === 0.5 ? 0.65 : layout === "split" && draft.top_ratio === 0.65 ? 0.5 : draft.top_ratio;
                set({ layout, top_ratio: ratio });
              }}>
                <option value="split">Pantalla partida (plano corto + escena)</option>
                <option value="full">Pantalla completa (abajo difuminado)</option>
                {draft.layout === "facecam" && <option value="facecam">Facecam (sin render)</option>}
              </select>
            </label>
            <label>Encuadre
              <select value={draft.focus} disabled={!editable} onChange={(e) => set({ focus: e.target.value as Draft["focus"] })}>
                <option value="left">Izquierda</option>
                <option value="center">Centro</option>
                <option value="right">Derecha</option>
              </select>
            </label>
          </div>
          <label>Zoom ×{draft.zoom.toFixed(2)}
            <input type="range" min={1} max={3} step={0.05} disabled={!editable} value={draft.zoom} onChange={(e) => set({ zoom: Number(e.target.value) })} />
          </label>
          <label>{draft.layout === "full" ? "Parte nítida" : "Parte superior"} {Math.round(draft.top_ratio * 100)} %
            <input type="range" min={0.2} max={0.9} step={0.05} disabled={!editable} value={draft.top_ratio} onChange={(e) => set({ top_ratio: Number(e.target.value) })} />
          </label>
          <label>Plantilla de marca
            <select disabled={!editable} value={draft.template_id === null ? "" : String(draft.template_id)}
              onChange={(e) => set({ template_id: e.target.value === "" ? null : Number(e.target.value) })}>
              <option value="">Sin plantilla (valores por defecto)</option>
              {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <span className="muted hint">Textos y colores de las cortinillas y estilo de los subtítulos. <Link to="/templates">Editar plantillas</Link></span>
          </label>
          <label className="check">
            <input type="checkbox" disabled={!editable} checked={draft.intro_enabled} onChange={(e) => set({ intro_enabled: e.target.checked })} />
            Cortinilla de inicio (opcional)
          </label>
          <p className="muted hint">Si la activas, entra tras la intro del clip y lo pausa 3,6 s. La cortinilla final se añade siempre.</p>
          {draft.intro_enabled && (
            <div className="cort-pos">
              <label>Posición de la cortinilla de inicio
                <select disabled={!editable} value={draft.cortinilla_at === null ? "auto" : String(draft.cortinilla_at)}
                  onChange={(e) => set({ cortinilla_at: e.target.value === "auto" ? null : Number(e.target.value) })}>
                  <option value="auto">Automática{options?.default != null ? ` (a los ${options.default.toFixed(1)} s)` : ""}</option>
                  {draft.cortinilla_at !== null && !options?.positions.some((p) => p.at === draft.cortinilla_at) && (
                    <option value={String(draft.cortinilla_at)}>{draft.cortinilla_at.toFixed(1)} s (guardada; se ajustará al silencio más cercano)</option>
                  )}
                  {options?.positions.map((p) => (
                    <option key={p.at} value={String(p.at)}>{p.at.toFixed(1)} s · {p.sentence ? "fin de frase" : "pausa"}{p.at < options.intro ? " · dentro de la intro" : ""}</option>
                  ))}
                </select>
              </label>
              <button type="button" className="ghost" disabled={draft.cortinilla_at === null && options?.default == null}
                onClick={() => seek(draft.start + (draft.cortinilla_at ?? options?.default ?? 0))}>Ver ese punto en el vídeo</button>
              {options && options.positions.length === 0 && <p className="error">No hay un silencio válido en este recorte: la cortinilla de inicio no entrará.</p>}
            </div>
          )}

          <div className="clip-actions">
            <button onClick={save} disabled={!editable || !dirty || !!problem || saving}>{saving ? "Guardando…" : "Guardar cambios"}</button>
            {clip.status === "detected" && <button disabled={dirty} title={dirty ? "Guarda antes de aprobar" : ""} onClick={() => transition("approve")}>Aprobar</button>}
            {clip.status === "approved" && <button className="ghost" onClick={() => transition("unapprove")}>Desaprobar</button>}
          </div>

          {clip.reason && <p className="muted"><strong>Por qué: </strong>{clip.reason}</p>}
          {clip.parts.length > 0 && <ol className="muted parts">{clip.parts.map((p, i) => <li key={i}>{p}</li>)}</ol>}
          {clip.emphasis.length > 0 && <div className="chips">{clip.emphasis.map((e, i) => <span className="chip" key={i} title={fmtTime(e.start)}>{e.text}</span>)}</div>}
        </div>
      </div>

      <RenderPanel clip={clip} dirty={dirty} editable={editable} onClip={setClip} />

      <section>
        <h2>Transcripción del tramo</h2>
        <p className="muted hint">Clic en una palabra para saltar a ella; después puedes poner el inicio o el fin del clip justo ahí. En gris, lo que queda fuera del clip.</p>
        {picked !== null && (
          <div className="selbar">
            <span>«{words[picked].text}» · {fmtTime(words[picked].start)}</span>
            <button disabled={!editable} onClick={() => { const v = round(Math.max(0, words[picked].start - 0.05)); set({ start: v }); seek(v); }}>Inicio aquí</button>
            <button disabled={!editable} onClick={() => set({ end: round(Math.min(project?.duration ?? Infinity, words[picked].end + 0.05)) })}>Fin aquí</button>
          </div>
        )}
        <p className="clip-words">
          {visible.map(({ i }) => {
            const w = words[i];
            const inside = w.start >= draft.start - 0.05 && w.end <= draft.end + 0.05;
            return (
              <span key={i} className={`word${inside ? "" : " out"}${i === activeIdx ? " active" : ""}${i === picked ? " sel" : ""}`}
                onClick={() => { setPicked(i); seek(w.start); }}>
                {w.text}{" "}
              </span>
            );
          })}
        </p>
      </section>
    </div>
  );
}
