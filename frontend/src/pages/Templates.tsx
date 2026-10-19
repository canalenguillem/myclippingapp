import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Asset, Template, TemplateCortinilla } from "../types";
import { EMPTY_CORTINILLA } from "../types";

// <hyperframes-player> es un elemento personalizado; se carga bajo demanda (pesa ~560 KB).
declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements { "hyperframes-player": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & { width?: number; height?: number; controls?: boolean; muted?: boolean }; }
  }
}
type PlayerEl = HTMLElement & { srcdoc?: string; seek?: (t: number) => void };

type Form = {
  name: string; preset: Template["preset"]; primary: string; sfx: boolean; cortinilla_default: boolean; cortinilla: TemplateCortinilla;
};
const DEFAULT_PRIMARY = "#DA2E09";
const blank = (): Form => ({ name: "Mi canal", preset: "editorial", primary: DEFAULT_PRIMARY, sfx: true, cortinilla_default: false, cortinilla: { ...EMPTY_CORTINILLA } });
const formOf = (t: Template): Form => ({
  name: t.name, preset: t.preset, primary: t.colors.primary ?? DEFAULT_PRIMARY, sfx: t.sfx, cortinilla_default: t.cortinilla_default,
  cortinilla: { ...EMPTY_CORTINILLA, ...t.cortinilla },
});
const bodyOf = (f: Form) => ({
  name: f.name, preset: f.preset, colors: { primary: f.primary }, sfx: f.sfx, cortinilla_default: f.cortinilla_default,
  cortinilla: { ...f.cortinilla, color: f.cortinilla.color || undefined, orbit_asset_id: f.cortinilla.orbit_asset_id || undefined },
});
const PREVIEW_DELAY_MS = 600;

export default function Templates() {
  const [list, setList] = useState<Template[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selected, setSelected] = useState<number | "new">("new");
  const [form, setForm] = useState<Form>(blank());
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [preview, setPreview] = useState<{ html: string; duration: number } | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [ready, setReady] = useState(false);
  const player = useRef<PlayerEl>(null);

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));
  const load = () => api<Template[]>("/api/templates").then(setList).catch(fail);
  useEffect(() => { api<Asset[]>("/api/assets").then(setAssets).catch(() => setAssets([])); }, []);
  useEffect(() => { load(); import("@hyperframes/player").then(() => setReady(true)).catch(fail); }, []);

  const choose = (t: Template | "new") => {
    setSelected(t === "new" ? "new" : t.id);
    setForm(t === "new" ? blank() : formOf(t));
    setNotice(""); setError("");
  };
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));
  const setC = (patch: Partial<TemplateCortinilla>) => setForm((f) => ({ ...f, cortinilla: { ...f.cortinilla, ...patch } }));

  // La vista previa se pide al servicio con lo que hay en el formulario (sin guardar y sin renderizar nada).
  useEffect(() => {
    const timer = setTimeout(() => {
      api<{ html: string; duration: number }>("/api/templates/preview", { json: { colors: { primary: form.primary }, cortinilla: { ...form.cortinilla, color: form.cortinilla.color || undefined, orbit_asset_id: form.cortinilla.orbit_asset_id || undefined } } })
        .then((r) => { setPreview(r); setPreviewError(""); })
        .catch((e) => setPreviewError(e instanceof Error ? e.message : String(e)));
    }, PREVIEW_DELAY_MS);
    return () => clearTimeout(timer);
  }, [form.primary, form.cortinilla]);

  useEffect(() => {
    if (ready && preview && player.current) player.current.setAttribute("srcdoc", preview.html);
  }, [ready, preview]);

  const save = async () => {
    setError(""); setNotice("");
    try {
      const saved = selected === "new"
        ? await api<Template>("/api/templates", { json: bodyOf(form) })
        : await api<Template>(`/api/templates/${selected}`, { method: "PATCH", json: bodyOf(form) });
      await load();
      setSelected(saved.id);
      setForm(formOf(saved));
      setNotice("Guardada. Los renders de los clips que la usan se han invalidado.");
    } catch (e) { fail(e); }
  };
  const remove = async () => {
    if (selected === "new" || !window.confirm("¿Borrar la plantilla? Los clips que la usan vuelven a la plantilla por defecto.")) return;
    try {
      await api(`/api/templates/${selected}`, { method: "DELETE" });
      await load();
      choose("new");
    } catch (e) { fail(e); }
  };
  const seek = (t: number) => player.current?.seek?.(t);

  return (
    <div className="page">
      <header className="bar"><Link to="/">← Inicio</Link><h1>Plantillas de marca</h1></header>
      <p className="muted hint">Los textos y colores de las cortinillas dependen de tu canal. La cortinilla final se añade siempre a los shorts; la de inicio es opcional por clip.</p>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      <div className="tpl">
        <div className="tpl-list">
          {list.map((t) => <button key={t.id} className={selected === t.id ? "" : "ghost"} onClick={() => choose(t)}>{t.name}</button>)}
          <button className={selected === "new" ? "" : "ghost"} onClick={() => choose("new")}>+ Nueva</button>
        </div>
        <div className="tpl-form">
          <label>Nombre<input value={form.name} maxLength={120} onChange={(e) => set({ name: e.target.value })} /></label>
          <div className="grid2">
            <label>Estilo
              <select value={form.preset} onChange={(e) => set({ preset: e.target.value as Form["preset"] })}>
                <option value="editorial">Editorial (banda de papel)</option>
                <option value="hormozi">Hormozi</option>
                <option value="minimal">Mínimo</option>
              </select>
            </label>
            <label>Color de marca<input type="color" value={form.primary} onChange={(e) => set({ primary: e.target.value.toUpperCase() })} /></label>
          </div>
          <h3>Cortinilla de inicio</h3>
          <label>Título (la última palabra sale en cursiva)<input value={form.cortinilla.title} maxLength={40} onChange={(e) => setC({ title: e.target.value })} /></label>
          <label>Antetítulo<input value={form.cortinilla.kicker} maxLength={60} onChange={(e) => setC({ kicker: e.target.value })} /></label>
          <label>Duración (s)<input type="number" min={1} max={10} step={0.1} value={form.cortinilla.duration} onChange={(e) => setC({ duration: Number(e.target.value) })} /></label>
          <label>Objeto que orbita por la píldora
            <select value={form.cortinilla.orbit_asset_id ?? ""} onChange={(e) => setC({ orbit_asset_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">Un cuadrado del color de marca</option>
              {assets.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
            <span className="muted hint">Elige una imagen de tu librería (se sube en el editor de un clip, «Mis imágenes»). Mejor un PNG con fondo transparente.</span>
          </label>
          <label className="check"><input type="checkbox" checked={form.cortinilla_default} onChange={(e) => set({ cortinilla_default: e.target.checked })} /> Activarla por defecto en los clips nuevos</label>
          <h3>Cortinilla final (siempre)</h3>
          <label>Llamada a la acción<input value={form.cortinilla.outro_text} maxLength={80} placeholder="Parte 2 en el canal" onChange={(e) => setC({ outro_text: e.target.value })} /></label>
          <label>Handle del canal<input value={form.cortinilla.handle} maxLength={40} placeholder="@micanal" onChange={(e) => setC({ handle: e.target.value })} /></label>
          <div className="grid2">
            <label>Botón 1<input value={form.cortinilla.like} maxLength={20} onChange={(e) => setC({ like: e.target.value })} /></label>
            <label>Botón 2<input value={form.cortinilla.subscribe} maxLength={20} onChange={(e) => setC({ subscribe: e.target.value })} /></label>
          </div>
          <label>Duración (s)<input type="number" min={1} max={10} step={0.1} value={form.cortinilla.outro_duration} onChange={(e) => setC({ outro_duration: Number(e.target.value) })} /></label>
          <label className="check"><input type="checkbox" checked={form.sfx} onChange={(e) => set({ sfx: e.target.checked })} /> Efectos de sonido en las cortinillas</label>
          <div className="clip-actions">
            <button onClick={save} disabled={!form.name.trim()}>{selected === "new" ? "Crear plantilla" : "Guardar cambios"}</button>
            {selected !== "new" && <button className="ghost" onClick={remove}>Borrar</button>}
          </div>
        </div>
        <div className="tpl-preview">
          <h3>Vista previa</h3>
          {previewError && <p className="error">{previewError}</p>}
          {ready && <hyperframes-player ref={player as never} width={1080} height={1920} controls muted style={{ display: "block", width: "100%", aspectRatio: "1080 / 1920", background: "#000", borderRadius: 10 }} />}
          <div className="clip-actions">
            <button className="ghost" onClick={() => seek(2.8)}>Cortinilla de inicio</button>
            <button className="ghost" onClick={() => seek(6.8)}>Cortinilla final</button>
          </div>
          <p className="muted hint">Clip de relleno: así entran y salen las cortinillas. El objeto que orbita (logo) se verá en el render real.</p>
        </div>
      </div>
    </div>
  );
}
