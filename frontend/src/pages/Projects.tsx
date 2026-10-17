import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Project } from "../types";

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

  const refresh = useCallback(() => {
    api<Project[]>("/api/projects").then(setProjects).catch((e) => setError(e.message));
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
      <table>
        <thead><tr><th>Vídeo</th><th>Duración</th><th>Estado</th><th /></tr></thead>
        <tbody>
          {projects.map((p) => (
            <tr key={p.id}>
              <td><Link to={`/projects/${p.id}`}>{p.title}</Link>{p.error && <div className="error">{p.error}</div>}</td>
              <td>{p.duration ? `${(p.duration / 60).toFixed(1)} min` : "—"}</td>
              <td><span className={`tag ${BUSY.has(p.status) ? "running" : p.status === "failed" ? "failed" : "completed"}`}>{STATUS_LABEL[p.status] ?? p.status}</span></td>
              <td><button className="ghost" disabled={BUSY.has(p.status)} onClick={() => remove(p)}>Borrar</button></td>
            </tr>
          ))}
          {projects.length === 0 && <tr><td colSpan={4} className="muted">Pega un enlace de YouTube para empezar.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
