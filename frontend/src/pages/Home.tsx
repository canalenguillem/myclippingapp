import { Link } from "react-router-dom";
import { useAuth } from "../auth";

export default function Home() {
  const { user, logout } = useAuth();
  return (
    <div className="card">
      <h1>ClippingVideos</h1>
      <p>Sesión: {user?.email} ({user?.role})</p>
      <p><Link to="/projects">Proyectos</Link> · <Link to="/channels">Canales</Link> · <Link to="/templates">Plantillas</Link> · <Link to="/jobs">Jobs</Link>{user?.role === "admin" && <> · <Link to="/admin">Usuarios</Link></>}</p>
      <button onClick={logout}>Salir</button>
    </div>
  );
}
