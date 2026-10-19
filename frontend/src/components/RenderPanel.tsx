import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Clip } from "../types";

type Job = { id: number; status: string; progress: number; error: string | null };
type QaCheck = { id: string; level: "ok" | "warn" | "error"; message: string };
type QaReport = { level: "ok" | "warn" | "error"; checks: QaCheck[]; contact: { url: string } | null };
type Qa = { draft: QaReport | null; final: QaReport | null };
type Urls = { draft: { url: string } | null; final: { url: string } | null; thumbnail: { url: string } | null };

type Props = {
  clip: Clip;
  /** Hay cambios sin guardar: el render saldría con lo guardado, no con lo que se ve en el formulario. */
  dirty: boolean;
  editable: boolean;
  onClip: (c: Clip) => void;
};

const POLL_MS = 2000;
const STILL_POINTS = [0, 0.25, 0.5, 0.75, 0.97];
const STATE_LABEL: Record<Clip["render_state"], string> = {
  none: "sin renderizar", rendering: "renderizando", draft: "borrador listo", final: "final listo", failed: "falló",
};

export default function RenderPanel({ clip, dirty, editable, onClip }: Props) {
  const [urls, setUrls] = useState<Urls | null>(null);
  const [qa, setQa] = useState<Qa | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [view, setView] = useState<"draft" | "final">("draft");
  const [error, setError] = useState("");
  const [stamp, setStamp] = useState(0);
  const prevState = useRef(clip.render_state);

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));
  const rendering = clip.render_state === "rendering";
  const canRender = clip.layout === "split" || clip.layout === "full";
  const duration = clip.end - clip.start;

  const reloadClip = useCallback(
    () => api<Clip>(`/api/clips/${clip.id}`).then(onClip).catch(fail),
    [clip.id, onClip],
  );

  // URLs firmadas del render; se piden de nuevo al terminar uno y antes de que caduquen (1 h).
  useEffect(() => {
    if (!clip.has_draft && !clip.has_final) { setUrls(null); return; }
    const load = () => api<Urls>(`/api/clips/${clip.id}/render-urls`).then(setUrls).catch(fail);
    load();
    const timer = setInterval(load, 50 * 60 * 1000);
    return () => clearInterval(timer);
  }, [clip.id, clip.has_draft, clip.has_final, clip.render_state]);

  // Revisión automática del render (comprobaciones y hoja de contactos); se vuelve a pedir al terminar un render.
  useEffect(() => {
    if (!clip.has_draft && !clip.has_final) { setQa(null); return; }
    api<Qa>(`/api/clips/${clip.id}/qa`).then(setQa).catch(() => setQa(null));
  }, [clip.id, clip.has_draft, clip.has_final, clip.render_state, stamp]);

  // Mientras se renderiza: progreso del job y estado del clip.
  useEffect(() => {
    if (!rendering) { setJob(null); return; }
    if (clip.render_job_id == null) {  // job ya cancelado o terminado, pero el handler aún no ha dejado el clip en un estado estable
      setJob(null);
      const timer = setInterval(reloadClip, POLL_MS);
      return () => clearInterval(timer);
    }
    let alive = true;
    const tick = async () => {
      try {
        const j = await api<Job>(`/api/jobs/${clip.render_job_id}`);
        if (!alive) return;
        setJob(j);
        if (["completed", "failed", "cancelled"].includes(j.status)) reloadClip();
      } catch (e) { if (alive) fail(e); }
    };
    tick();
    const timer = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [rendering, clip.render_job_id, reloadClip]);

  // Si el render acaba, los fotogramas sueltos y el vídeo deben refrescarse.
  useEffect(() => {
    if (prevState.current === "rendering" && clip.render_state !== "rendering") setStamp((s) => s + 1);
    prevState.current = clip.render_state;
  }, [clip.render_state]);

  const start = async (quality: "draft" | "final") => {
    setError("");
    try {
      await api<{ job_id: number }>(`/api/clips/${clip.id}/render`, { json: { quality } });
      setView(quality);
      await reloadClip();
    } catch (e) { fail(e); }
  };
  const cancel = async () => {
    setError("");
    try {
      await api(`/api/clips/${clip.id}/render/cancel`, { method: "POST" });
      await reloadClip();
    } catch (e) { fail(e); }
  };

  const shown = urls?.[view] ?? urls?.draft ?? urls?.final ?? null;
  const shownQuality: "draft" | "final" = urls?.[view] ? view : urls?.draft ? "draft" : "final";
  const warning = clip.render_error?.startsWith("Aviso:") ? clip.render_error : "";
  const failure = clip.render_error && !warning ? clip.render_error : "";
  const canDraft = editable && !dirty && !rendering && canRender;
  const canFinal = canDraft && clip.status === "approved";

  return (
    <section className="render-panel">
      <h2>Render <span className={`tag ${clip.render_state === "failed" ? "failed" : clip.render_state === "rendering" ? "running" : clip.render_state === "none" ? "" : "completed"}`}>{STATE_LABEL[clip.render_state]}</span></h2>
      {!canRender && <p className="muted hint">El render admite pantalla partida y pantalla completa; cambia el diseño y guarda.</p>}
      {dirty && <p className="muted hint">Guarda los cambios antes de renderizar: el render usa lo guardado.</p>}
      {error && <p className="error">{error}</p>}
      {failure && <p className="error">El último render falló: {failure}</p>}
      {warning && <p className="notice">{warning}</p>}

      <div className="clip-actions">
        <button disabled={!canDraft} onClick={() => start("draft")}>{clip.has_draft ? "Renderizar borrador otra vez" : "Renderizar borrador"}</button>
        <button disabled={!canFinal} title={clip.status === "approved" ? "" : "Aprueba el clip para el render final"} onClick={() => start("final")}>
          {clip.has_final ? "Renderizar final otra vez" : "Render final"}
        </button>
        {rendering && <button className="ghost" onClick={cancel}>Cancelar render</button>}
      </div>

      {rendering && (
        <p>
          <progress max={100} value={job?.progress ?? 0} /> {job?.progress ?? 0} %
          <span className="muted"> {job?.status === "queued" ? "en cola (esperando el carril de render)" : "renderizando"}</span>
        </p>
      )}

      {shown && (
        <div className="render-view">
          {clip.has_draft && clip.has_final && (
            <div className="clip-actions">
              <button className={view === "draft" ? "" : "ghost"} onClick={() => setView("draft")}>Borrador</button>
              <button className={view === "final" ? "" : "ghost"} onClick={() => setView("final")}>Final</button>
            </div>
          )}
          <a className="btn" href={shown.url} download={`short_${clip.id}_${shownQuality === "final" ? "final" : "borrador"}.mp4`}>
            Descargar {shownQuality === "final" ? "el vídeo final" : "el borrador"}
          </a>
          <video key={shown.url.split("?")[0] + stamp} src={shown.url} controls playsInline className="render-video" />
          {qa?.[shownQuality] && (
            <div className={`qa qa-${qa[shownQuality]!.level}`}>
              <strong>Revisión automática {qa[shownQuality]!.level === "ok" ? "✔ todo correcto" : qa[shownQuality]!.level === "warn" ? "⚠ avisos" : "✖ hay fallos"}</strong>
              <ul>
                {qa[shownQuality]!.checks.map((c) => <li key={c.id} className={`qa-${c.level}`}>{c.level === "ok" ? "✔" : c.level === "warn" ? "⚠" : "✖"} {c.message}</li>)}
              </ul>
              {qa[shownQuality]!.contact && (
                <a href={qa[shownQuality]!.contact!.url} target="_blank" rel="noreferrer" title="Abrir la hoja de contactos a tamaño completo">
                  <img className="qa-contact" alt="Hoja de contactos del render (un fotograma cada 2,5 s)" loading="lazy" src={qa[shownQuality]!.contact!.url} />
                </a>
              )}
            </div>
          )}
          <div className="stills">
            {STILL_POINTS.map((p) => {
              const t = Math.min(duration - 0.1, p * duration);
              return (
                <figure key={p}>
                  <img alt={`Fotograma a ${t.toFixed(1)} s`} loading="lazy"
                    src={`/api/clips/${clip.id}/still?t=${t.toFixed(2)}&quality=${shownQuality}&v=${stamp}`} />
                  <figcaption className="muted">{t.toFixed(1)} s</figcaption>
                </figure>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
