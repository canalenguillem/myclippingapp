import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Project } from "../types";

type StorageInfo = { free_bytes: number; total_bytes: number; retention_days: number; projects: { id: number; bytes: number; heavy_bytes: number; has_source: boolean }[] };
export const fmtBytes = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${Math.round(n / 1e6)} MB` : `${Math.max(0, Math.round(n / 1e3))} KB`);

const BUSY = new Set(["downloading", "transcribing"]);
export const STATUS_LABEL: Record<string, string> = {
  downloading: "Descargando", transcribing: "Transcribiendo",
  detecting: "Detectando clips", ready: "Listo", failed: "Falló",
};

export default function Projects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [url, setUrl] = useState("");
  const [language, setLanguage] = useState("auto");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [disk, setDisk] = useState<StorageInfo | null>(null);
  const [notice, setNotice] = useState("");

  const refresh = useCallback(() => {
    api<Project[]>("/api/projects").then(setProjects).catch((e) => setError(e.message));
    api<StorageInfo>("/api/storage").then(setDisk).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/projects", { json: { source_url: url, language } });
      setUrl("");
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const free = async (p: Project, heavy: number) => {
    if (!confirm(`¿Liberar ${fmtBytes(heavy)} de «${p.title}»?\n\nSe borran el vídeo original y los renders. Se descargan de nuevo solos al volver a renderizar un clip; la transcripción, los clips y los gráficos se conservan.`)) return;
    setError(""); setNotice("");
    try {
      const r = await api<{ freed_bytes: number }>(`/api/projects/${p.id}/free-space`, { method: "POST" });
      setNotice(r.freed_bytes ? `Liberados ${fmtBytes(r.freed_bytes)}` : "Nada que liberar ahora (¿hay un job en marcha?)");
      refresh();
    } catch (err) { setError((err as Error).message); }
  };

  const remove = async (p: Project) => {
    if (!confirm(`¿Borrar «${p.title}» y todos sus ficheros?`)) return;
    try {
      await api(`/api/projects/${p.id}`, { method: "DELETE" });
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="page">
      <header className="bar">
        <Link to="/">← Inicio</Link>
        <h1>Proyectos</h1>
      </header>
      <form className="row" onSubmit={submit}>
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.youtube.com/watch?v=…" required />
        <select value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="Idioma">
          <option value="auto">Idioma: auto</option>
          <option value="es">Español</option>
          <option value="en">English</option>
        </select>
        <button disabled={busy}>Importar</button>
      </form>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {disk && (
        <p className="muted">
          Disco: {fmtBytes(disk.free_bytes)} libres de {fmtBytes(disk.total_bytes)}.
          {disk.retention_days > 0 ? ` Lo pesado de un proyecto (vídeo original y renders) se borra solo tras ${disk.retention_days} días sin actividad y se descarga de nuevo al renderizar.` : " La limpieza automática está desactivada."}
        </p>
      )}
      <table>
        <thead><tr><th>Vídeo</th><th>Duración</th><th>Estado</th><th>Disco</th><th /></tr></thead>
        <tbody>
          {projects.map((p) => (
            <tr key={p.id}>
              <td><Link to={`/projects/${p.id}`}>{p.title}</Link>{p.error && <div className="error">{p.error}</div>}</td>
              <td>{p.duration ? `${(p.duration / 60).toFixed(1)} min` : "—"}</td>
              <td><span className={`tag ${BUSY.has(p.status) ? "running" : p.status === "failed" ? "failed" : "completed"}`}>{STATUS_LABEL[p.status] ?? p.status}</span></td>
              <td className="muted">{(() => { const u = disk?.projects.find((x) => x.id === p.id); return u ? fmtBytes(u.bytes) : "—"; })()}</td>
              <td>
                {(() => { const u = disk?.projects.find((x) => x.id === p.id); return u && u.heavy_bytes > 0 ? <button className="ghost" disabled={BUSY.has(p.status)} onClick={() => free(p, u.heavy_bytes)} title="Borra el vídeo original y los renders (se regeneran)">Liberar {fmtBytes(u.heavy_bytes)}</button> : null; })()}
                {" "}<button className="ghost" disabled={BUSY.has(p.status)} onClick={() => remove(p)}>Borrar</button>
              </td>
            </tr>
          ))}
          {projects.length === 0 && <tr><td colSpan={5} className="muted">Pega un enlace de YouTube para empezar.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
