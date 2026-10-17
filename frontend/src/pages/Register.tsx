import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function Register() {
  const { user, register } = useAuth();
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await register(email, password, name);
      nav("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card auth" onSubmit={submit}>
      <h1>Crear cuenta</h1>
      <label>Nombre<input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></label>
      <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
      <label>Contraseña (mín. 8)<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} /></label>
      {error && <p className="error">{error}</p>}
      <button disabled={busy}>{busy ? "Creando…" : "Crear cuenta"}</button>
      <p className="muted">¿Ya tienes cuenta? <Link to="/login">Entrar</Link></p>
    </form>
  );
}
