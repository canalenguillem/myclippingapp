import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Channel, Clip } from "../types";

type Props = { clip: Clip; dirty: boolean; onClip: (c: Clip) => void };
type Job = { status: string; progress: number };
const PRIVACY = { private: "Privado", unlisted: "No listado", public: "Público" } as const;
const POLL_MS = 2000;
const pad = (n: number) => String(n).padStart(2, "0");
const toLocal = (iso: string | null) => {   // ISO UTC del servidor → valor de <input type=datetime-local> en hora local
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export default function YouTubePanel({ clip, dirty, onClip }: Props) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelId, setChannelId] = useState<number | null>(clip.channel_id);
  const [title, setTitle] = useState(clip.seo_title);
  const [description, setDescription] = useState(clip.seo_description);
  const [tags, setTags] = useState(clip.seo_tags.join(", "));
  const [privacy, setPrivacy] = useState<Clip["privacy"]>(clip.privacy);
  const [when, setWhen] = useState(toLocal(clip.publish_at));
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [job, setJob] = useState<Job | null>(null);

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));
  const uploading = clip.status === "uploading";
  const uploaded = clip.status === "uploaded" || !!clip.youtube_video_id;
  const hasFinal = clip.render_state === "final" && clip.has_final;
  const hasDraft = clip.has_draft && (clip.render_state === "draft" || clip.render_state === "final");
  // por defecto se sube el final; si solo hay borrador (540x960), se sube ese, avisando de la calidad
  const [source, setSource] = useState<"final" | "draft">(hasFinal ? "final" : "draft");
  const chosen: "final" | "draft" = source === "final" && !hasFinal ? "draft" : source === "draft" && !hasDraft ? "final" : source;
  const canEdit = clip.status === "approved" && !uploading;

  useEffect(() => { api<Channel[]>("/api/channels").then(setChannels).catch(() => setChannels([])); }, []);
  const linked = channels.filter((c) => c.linked);
  const channel = channels.find((c) => c.id === channelId) ?? null;
  useEffect(() => { if (channelId === null && linked.length === 1) setChannelId(linked[0].id); }, [linked.length]);  // eslint-disable-line react-hooks/exhaustive-deps

  // mientras sube: progreso del job y estado del clip
  useEffect(() => {
    if (!uploading) { setJob(null); return; }
    let alive = true;
    const tick = async () => {
      try {
        if (clip.upload_job_id) { const j = await api<Job>(`/api/jobs/${clip.upload_job_id}`); if (alive) setJob(j); }
        const c = await api<Clip>(`/api/clips/${clip.id}`);
        if (alive && c.status !== "uploading") onClip(c);
      } catch (e) { if (alive) fail(e); }
    };
    tick();
    const timer = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [uploading, clip.upload_job_id, clip.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  const body = () => ({
    channel_id: channelId, title, description, tags: tags.split(",").map((t) => t.trim()).filter(Boolean), privacy,
    publish_at: when ? new Date(when).toISOString() : null,
  });
  const generate = async () => {
    if (channelId === null) return;
    setError(""); setNotice(""); setBusy("generate");
    try {
      const r = await api<{ title: string; description: string; tags: string[]; source: string }>(`/api/clips/${clip.id}/seo/generate`, { json: { channel_id: channelId } });
      setTitle(r.title); setDescription(r.description); setTags(r.tags.join(", "));
      setNotice(r.source === "model" ? "Textos propuestos por el modelo: revísalos y edítalos antes de subir." : "No se pudo usar el modelo (¿falta la clave de OpenAI?): te propongo unos textos básicos, edítalos.");
    } catch (e) { fail(e); } finally { setBusy(""); }
  };
  const save = async (): Promise<Clip | null> => {
    setError(""); setNotice(""); setBusy("save");
    try {
      const c = await api<Clip>(`/api/clips/${clip.id}/seo`, { method: "PUT", json: body() });
      onClip(c);
      setTitle(c.seo_title); setDescription(c.seo_description); setTags(c.seo_tags.join(", "));
      setNotice("Textos guardados.");
      return c;
    } catch (e) { fail(e); return null; } finally { setBusy(""); }
  };
  const upload = async () => {
    if (channel === null) return;
    const saved = await save();      // se sube lo que se ve: primero se guarda
    if (!saved) return;
    const when2 = saved.publish_at ? `se publicará el ${new Date(saved.publish_at.endsWith("Z") ? saved.publish_at : saved.publish_at + "Z").toLocaleString()}` : `quedará ${PRIVACY[saved.privacy].toLowerCase()}`;
    const quality = chosen === "draft" ? "\nVídeo: el BORRADOR (540×960, menos calidad que el final)" : "\nVídeo: el render final (1080×1920)";
    if (!window.confirm(`¿Subir a YouTube?\n\nCanal: ${channel.yt_title ?? channel.name}\nTítulo: ${saved.seo_title}\n${when2}${quality}`)) return;
    setBusy("upload");
    try {
      await api(`/api/clips/${clip.id}/upload`, { json: { channel_id: channel.id, source: chosen } });
      onClip(await api<Clip>(`/api/clips/${clip.id}`));
    } catch (e) { fail(e); } finally { setBusy(""); }
  };

  if (!hasFinal && !hasDraft && !uploaded) {
    return <section className="yt-panel"><h2>Subir a YouTube</h2><p className="muted hint">Primero renderiza el clip (un <strong>borrador</strong> para subirlo ya, o el <strong>render final</strong> para la mejor calidad).</p></section>;
  }
  if (clip.status !== "approved" && !uploading && !uploaded) {
    return <section className="yt-panel"><h2>Subir a YouTube</h2><p className="muted hint">Aprueba el clip para poder subirlo.</p></section>;
  }

  return (
    <section className="yt-panel">
      <h2>Subir a YouTube {uploaded && <span className="tag completed">subido</span>}{uploading && <span className="tag running">subiendo</span>}</h2>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {clip.upload_error && !uploaded && <p className="error">La última subida falló: {clip.upload_error}</p>}

      {uploaded ? (
        <p>El clip ya está en YouTube{clip.uploaded_at ? ` (${new Date(clip.uploaded_at.endsWith("Z") ? clip.uploaded_at : clip.uploaded_at + "Z").toLocaleString()})` : ""}:{" "}
          <a href={`https://www.youtube.com/shorts/${clip.youtube_video_id}`} target="_blank" rel="noreferrer">youtube.com/shorts/{clip.youtube_video_id}</a>
          {" · "}<a href="https://studio.youtube.com/" target="_blank" rel="noreferrer">YouTube Studio</a>
        </p>
      ) : (
        <>
          {linked.length === 0 ? (
            <p className="error">No hay ningún canal conectado. <Link to="/channels">Conecta uno en Canales</Link>.</p>
          ) : (
            <label>Canal de destino
              <select value={channelId ?? ""} disabled={!canEdit} onChange={(e) => setChannelId(e.target.value ? Number(e.target.value) : null)}>
                <option value="">Elige un canal…</option>
                {linked.map((c) => <option key={c.id} value={c.id}>{c.yt_title ?? c.name}{c.yt_title && c.yt_title !== c.name ? ` (en la app: ${c.name})` : ""}</option>)}
              </select>
            </label>
          )}
          {channel && channel.yt_title && channel.yt_title.toLowerCase() !== channel.name.toLowerCase() && (
            <p className="yt-warn">⚠ Este canal de la app se llama «{channel.name}», pero la cuenta conectada es el canal de YouTube «{channel.yt_title}». Si no es el que quieres, reconéctalo eligiendo la cuenta correcta en <Link to="/channels">Canales</Link>.</p>
          )}
          {channel && <p className="yt-target">Se subirá a: <strong>{channel.yt_title ?? channel.name}</strong></p>}
          <fieldset className="yt-source" disabled={!canEdit}>
            <legend>Vídeo que se sube</legend>
            <label className="check"><input type="radio" name={`src${clip.id}`} checked={chosen === "final"} disabled={!hasFinal} onChange={() => setSource("final")} />
              Render final (1080×1920){!hasFinal && " — aún no hay"}</label>
            <label className="check"><input type="radio" name={`src${clip.id}`} checked={chosen === "draft"} disabled={!hasDraft} onChange={() => setSource("draft")} />
              Borrador (540×960, menos calidad){!hasDraft && " — aún no hay"}</label>
          </fieldset>
          {chosen === "draft" && <p className="yt-warn">El borrador se ve más blando (la mitad de resolución y más compresión). Para el mejor resultado haz antes el «Render final».</p>}
          <div className="clip-actions">
            <button className="ghost" onClick={generate} disabled={!canEdit || channelId === null || busy !== ""}>{busy === "generate" ? "Generando…" : "Generar textos con IA"}</button>
          </div>
          <label>Título ({title.length}/100)<input value={title} maxLength={100} disabled={!canEdit} onChange={(e) => setTitle(e.target.value)} /></label>
          <label>Descripción
            <textarea rows={5} value={description} maxLength={4900} disabled={!canEdit} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <label>Etiquetas (separadas por comas)<input value={tags} disabled={!canEdit} onChange={(e) => setTags(e.target.value)} /></label>
          <div className="grid2">
            <label>Privacidad
              <select value={privacy} disabled={!canEdit || !!when} onChange={(e) => setPrivacy(e.target.value as Clip["privacy"])}>
                {Object.entries(PRIVACY).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label>Programar publicación (opcional)
              <input type="datetime-local" value={when} disabled={!canEdit} onChange={(e) => { setWhen(e.target.value); if (e.target.value) setPrivacy("private"); }} />
            </label>
          </div>
          <p className="muted hint">Si Google no ha auditado tu proyecto de la API, el vídeo queda en privado aunque elijas «Público»: pásalo a público en YouTube Studio. Los textos los generó un modelo: léelos antes de subir.</p>
          {uploading && <p><progress max={100} value={job?.progress ?? 0} /> {job?.progress ?? 0} % <span className="muted">subiendo…</span></p>}
          <div className="clip-actions">
            <button className="ghost" onClick={save} disabled={!canEdit || channelId === null || !title.trim() || busy !== ""}>Guardar textos</button>
            <button onClick={upload} disabled={!canEdit || channelId === null || !title.trim() || busy !== "" || dirty} title={dirty ? "Guarda antes los cambios del clip" : ""}>
              {busy === "upload" ? "Subiendo…" : "Subir a YouTube"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
