import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import ClipEditor from "./pages/ClipEditor";
import Home from "./pages/Home";
import Jobs from "./pages/Jobs";
import ProjectDetail from "./pages/ProjectDetail";
import Projects from "./pages/Projects";
import Templates from "./pages/Templates";
import Login from "./pages/Login";
import Register from "./pages/Register";

function RequireAuth() {
  const { user, loading } = useAuth();
  if (loading) return <p className="center">Cargando…</p>;
  return user ? <Outlet /> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<Home />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/templates" element={<Templates />} />
          <Route path="/clips/:id" element={<ClipEditor />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
