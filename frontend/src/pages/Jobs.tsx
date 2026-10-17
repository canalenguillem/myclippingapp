import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

type Job = {
  id: number; type: string; status: string; progress: number; error: string | null;
  attempts: number; created_at: string | null; started_at: string | null; ended_at: string | null;
};

const ACTIVE = new Set(["queued", "running"]);

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [error, setError] = useState("");
  const logRef = useRef<HTMLPreElement>(null);

  const refresh = useCallback(() => {
    api<Job[]>("/api/jobs").then(setJobs).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [refresh]);

  // Log en vivo del job seleccionado (SSE; la cookie de sesion viaja sola, mismo origen).
  useEffect(() => {
    if (selected === null) return;
    setLog([]);
    const es = new EventSource(`/api/jobs/${selected}/stream`);
    es.addEventListener("log", (e) => setLog((l) => [...l, JSON.parse((e as MessageEvent).data)]));
    es.addEventListener("status", refresh);
    es.onerror = () => es.close(); // el servidor cierra el stream al terminar el job
    return () => es.close();
  }, [selected, refresh]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [log]);

  const create = async () => {
    try {
      await api("/api/jobs", { json: { type: "demo", payload: { seconds: 10 } } });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const cancel = async (id: number) => {
    try {
      await api(`/api/jobs/${id}/cancel`, { method: "POST" });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="page">
      <header className="bar">
        <Link to="/">← Inicio</Link>
        <h1>Jobs</h1>
        <button onClick={create}>Lanzar demo (10 s)</button>
      </header>
      {error && <p className="error">{error}</p>}
      <table>
        <thead><tr><th>#</th><th>Tipo</th><th>Estado</th><th>Progreso</th><th>Error</th><th /></tr></thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id} className={j.id === selected ? "sel" : ""} onClick={() => setSelected(j.id)}>
              <td>{j.id}</td>
              <td>{j.type}</td>
              <td><span className={`tag ${j.status}`}>{j.status}</span></td>
              <td><progress max={100} value={j.progress} /> {j.progress}%</td>
              <td className="error">{j.error}</td>
              <td>{ACTIVE.has(j.status) && <button className="ghost" onClick={(e) => { e.stopPropagation(); cancel(j.id); }}>Cancelar</button>}</td>
            </tr>
          ))}
          {jobs.length === 0 && <tr><td colSpan={6} className="muted">Sin jobs todavía.</td></tr>}
        </tbody>
      </table>
      {selected !== null && <pre ref={logRef} className="log">{log.join("\n") || "…"}</pre>}
    </div>
  );
}
