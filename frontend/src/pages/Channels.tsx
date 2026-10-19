import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { Channel } from "../types";

const PRIVACY: Record<Channel["default_privacy"], string> = { private: "Privado", unlisted: "No listado", public: "Público" };

function ChannelCard({ ch, onChange, onError, onNotice }: { ch: Channel; onChange: () => void; onError: (m: string) => void; onNotice: (m: string) => void }) {
  const [draft, setDraft] = useState({ name: ch.name, language: ch.language, default_privacy: ch.default_privacy, seo_rules: ch.seo_rules });
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify({ name: ch.name, language: ch.language, default_privacy: ch.default_privacy, seo_rules: ch.seo_rules });
  const fail = (e: unknown) => onError(e instanceof Error ? e.message : String(e));

  const save = async () => {
    try { await api(`/api/channels/${ch.id}`, { method: "PATCH", json: draft }); onNotice("Cambios guardados"); onChange(); } catch (e) { fail(e); }
  };
  const uploadSecret = async (file: File | undefined) => {
    if (!file) return;
    if (ch.linked && !window.confirm("Este canal ya está conectado. Si cambias el client_secret.json se desconectará y tendrás que volver a conectarlo. ¿Seguir?")) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      await api(`/api/channels/${ch.id}/client-secret`, { method: "PUT", body: fd });
      onNotice("client_secret.json guardado (cifrado). Ahora pulsa «Conectar con YouTube».");
      onChange();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const removeSecret = async () => {
    if (!window.confirm("¿Quitar el client_secret.json de este canal? También se desconecta de YouTube.")) return;
    try { await api(`/api/channels/${ch.id}/client-secret`, { method: "DELETE" }); onChange(); } catch (e) { fail(e); }
  };
  const connect = async () => {
    setBusy(true);
    try {
      const r = await api<{ url: string }>(`/api/channels/${ch.id}/oauth/start`);
      window.location.href = r.url;   // Google devuelve al usuario a /api/youtube/callback y de ahí a esta página
    } catch (e) { fail(e); setBusy(false); }
  };
  const disconnect = async () => {
    if (!window.confirm("¿Desconectar este canal de YouTube? Podrás volver a conectarlo cuando quieras.")) return;
    try { await api(`/api/channels/${ch.id}/token`, { method: "DELETE" }); onChange(); } catch (e) { fail(e); }
  };
  const remove = async () => {
    if (!window.confirm(`¿Borrar el canal «${ch.name}» de la app? (No borra nada en YouTube.)`)) return;
    try { await api(`/api/channels/${ch.id}`, { method: "DELETE" }); onChange(); } catch (e) { fail(e); }
  };

  return (
    <section className="chan-card">
      <header className="chan-head">
        {ch.linked && ch.yt_thumbnail ? <img src={ch.yt_thumbnail} alt="" className="chan-avatar" /> : <div className="chan-avatar empty" />}
        <div>
          <strong>{ch.name}</strong>
          <div className="muted">{ch.linked ? `Conectado como «${ch.yt_title}»` : ch.has_secret ? "client_secret guardado; falta conectar" : "Sin client_secret.json"}</div>
        </div>
        <span className={`tag ${ch.linked ? "completed" : ""}`}>{ch.linked ? "conectado" : "sin conectar"}</span>
      </header>

      <div className="grid2">
        <label>Nombre<input value={draft.name} maxLength={120} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
        <label>Idioma (2 letras)<input value={draft.language} maxLength={2} onChange={(e) => setDraft({ ...draft, language: e.target.value.toLowerCase() })} /></label>
      </div>
      <label>Privacidad por defecto
        <select value={draft.default_privacy} onChange={(e) => setDraft({ ...draft, default_privacy: e.target.value as Channel["default_privacy"] })}>
          {Object.entries(PRIVACY).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>
      <label>Reglas de SEO del canal (opcional)
        <textarea rows={2} value={draft.seo_rules} maxLength={2000} placeholder="Tono, palabras a evitar, etiquetas fijas…" onChange={(e) => setDraft({ ...draft, seo_rules: e.target.value })} />
      </label>
      <div className="clip-actions"><button onClick={save} disabled={!dirty || !draft.name.trim()}>Guardar</button></div>

      <h3>Conexión con YouTube</h3>
      <p className="muted hint">
        Cada canal usa el <code>client_secret.json</code> de su propio proyecto de Google Cloud (API de YouTube Data v3 activada). Se guarda cifrado y no se
        vuelve a mostrar. En Google Cloud, en tu ID de cliente OAuth, añade este URI en «URIs de redireccionamiento autorizados»:
      </p>
      <div className="chan-uri"><code>{ch.redirect_uri}</code>
        <button className="ghost" onClick={() => { navigator.clipboard?.writeText(ch.redirect_uri); onNotice("URI copiado"); }}>Copiar</button>
      </div>
      <div className="clip-actions">
        <label className="gfx-upload">
          <input type="file" accept="application/json,.json" disabled={busy} onChange={(e) => { uploadSecret(e.target.files?.[0]); e.target.value = ""; }} />
          {ch.has_secret ? "Cambiar client_secret.json" : "Subir client_secret.json"}
        </label>
        {ch.has_secret && <button className="ghost" onClick={removeSecret}>Quitar JSON</button>}
        <button onClick={connect} disabled={!ch.has_secret || busy}>{ch.linked ? "Reconectar con otra cuenta" : "Conectar con YouTube"}</button>
        {ch.linked && <button className="ghost" onClick={disconnect}>Desconectar</button>}
      </div>
      {ch.secret_hint && <p className="muted">JSON actual: {ch.secret_hint}</p>}
      <details className="muted"><summary>Avisos de Google</summary>
        <ul>
          <li>Si la pantalla de consentimiento está en «Testing», el acceso caduca a los 7 días y hay que reconectar; añade tu cuenta como usuario de prueba o publica la app.</li>
          <li>Los vídeos subidos por la API desde un proyecto sin auditar se quedan en <strong>privado</strong> aunque pidamos «público»: pásalos a público en YouTube Studio.</li>
          <li>Cuota: unas 6 subidas al día por proyecto de Google.</li>
        </ul>
      </details>
      <div className="clip-actions"><button className="ghost" onClick={remove}>Borrar canal</button></div>
    </section>
  );
}

export default function Channels() {
  const [list, setList] = useState<Channel[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [name, setName] = useState("");
  const [params, setParams] = useSearchParams();
  const load = () => api<Channel[]>("/api/channels").then(setList).catch((e) => setError(e instanceof Error ? e.message : String(e)));

  useEffect(() => {
    load();
    // vuelta del OAuth: /channels?linked=ID o /channels?error=mensaje
    if (params.get("linked")) setNotice("¡Canal conectado con YouTube!");
    if (params.get("error")) setError(`No se pudo conectar: ${params.get("error")}`);
    if (params.get("linked") || params.get("error")) setParams({}, { replace: true });
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const create = async () => {
    setError("");
    try { await api("/api/channels", { json: { name: name.trim() } }); setName(""); load(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  return (
    <div className="page">
      <header className="bar"><Link to="/">← Inicio</Link><h1>Canales de YouTube</h1></header>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      <div className="chan-new">
        <input placeholder="Nombre del canal (p. ej. Spain Facts)" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) create(); }} />
        <button onClick={create} disabled={!name.trim()}>Añadir canal</button>
      </div>
      {list.length === 0 && <p className="muted">Aún no tienes canales. Añade uno, sube su client_secret.json y conéctalo.</p>}
      {list.map((ch) => <ChannelCard key={ch.id} ch={ch} onChange={load} onError={(m) => { setNotice(""); setError(m); }} onNotice={(m) => { setError(""); setNotice(m); }} />)}
    </div>
  );
}
