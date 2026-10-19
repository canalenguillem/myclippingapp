import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

type AdminUser = {
  id: number; email: string; name: string; role: string; is_active: boolean; max_concurrent_jobs: number; max_video_minutes: number;
  running_jobs: number; queued_jobs: number;
};
type Data = { render_lanes: number; users: AdminUser[] };

export default function Admin() {
  const { user } = useAuth();
  const [data, setData] = useState<Data | null>(null);
  const [draft, setDraft] = useState<Record<number, Partial<AdminUser>>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = () => api<Data>("/api/admin/users").then(setData).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);

  if (user && user.role !== "admin") return <div className="page"><p className="error">Solo para administradores.</p><Link to="/">← Inicio</Link></div>;

  const save = async (u: AdminUser) => {
    setError(""); setNotice("");
    try {
      await api<AdminUser>(`/api/admin/users/${u.id}`, { method: "PATCH", json: draft[u.id] });
      setDraft((d) => { const { [u.id]: _gone, ...rest } = d; return rest; });
      setNotice(`Guardado: ${u.email}`);
      load();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  const set = (id: number, patch: Partial<AdminUser>) => setDraft((d) => ({ ...d, [id]: { ...d[id], ...patch } }));

  return (
    <div className="page">
      <div className="bar"><Link to="/">← Inicio</Link><h1>Usuarios</h1></div>
      {data && (
        <p className="muted">
          Renders a la vez en todo el sistema: <strong>{data.render_lanes}</strong> (se cambia con <code>RENDER_LANES</code> en el <code>.env</code> del servidor).
          «Jobs a la vez» es lo que puede tener en marcha cada usuario; las subidas a YouTube no cuentan.
        </p>
      )}
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      <table>
        <thead><tr><th>Usuario</th><th>Rol</th><th>Jobs a la vez</th><th>Máx. minutos de vídeo</th><th>Activo</th><th>Ahora</th><th /></tr></thead>
        <tbody>
          {data?.users.map((u) => {
            const d = draft[u.id] ?? {};
            const dirty = Object.keys(d).length > 0;
            return (
              <tr key={u.id} style={{ cursor: "default" }}>
                <td>{u.email}{u.name ? <span className="muted"> · {u.name}</span> : null}</td>
                <td>{u.role}</td>
                <td><input type="number" min={1} max={8} style={{ width: 70 }} value={d.max_concurrent_jobs ?? u.max_concurrent_jobs} onChange={(e) => set(u.id, { max_concurrent_jobs: Number(e.target.value) })} /></td>
                <td><input type="number" min={1} max={1000} style={{ width: 90 }} value={d.max_video_minutes ?? u.max_video_minutes} onChange={(e) => set(u.id, { max_video_minutes: Number(e.target.value) })} /></td>
                <td><input type="checkbox" checked={d.is_active ?? u.is_active} disabled={u.id === user?.id} onChange={(e) => set(u.id, { is_active: e.target.checked })} /></td>
                <td className="muted">{u.running_jobs} en marcha · {u.queued_jobs} en cola</td>
                <td><button disabled={!dirty} onClick={() => save(u)}>Guardar</button></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
