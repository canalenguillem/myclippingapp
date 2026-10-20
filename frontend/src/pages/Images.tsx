import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, apiBlob } from "../api";
import CountryMaps from "../components/CountryMaps";
import type { Asset } from "../types";

type Box = { x: number; y: number; w: number; h: number };
type Shape = "rect" | "ellipse" | "circle";
const FULL: Box = { x: 0, y: 0, w: 1, h: 1 };
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const isFull = (b: Box) => b.x === 0 && b.y === 0 && b.w === 1 && b.h === 1;

export default function Images() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [selected, setSelected] = useState<Asset | null>(null);
  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  const load = useCallback(() => api<Asset[]>("/api/assets").then(setAssets).catch(fail), []);
  useEffect(() => { load(); }, [load]);

  const upload = async (input: FileList | File[]) => {
    const files = Array.from(input);          // la FileList se vacía al resetear el input: se copia antes
    setError(""); setNotice(""); setUploading(true);
    let last: Asset | null = null;
    try {
      for (const file of files) {
        const fd = new FormData();
        fd.append("file", file);
        last = await api<Asset>("/api/assets", { method: "POST", body: fd });
      }
      await load();
      if (last) { setSelected(last); setNotice(files.length > 1 ? `Subidas ${files.length} imágenes` : `Subida «${last.name}»`); }
    } catch (e) { fail(e); await load(); } finally { setUploading(false); }
  };

  const rename = async (a: Asset, name: string) => {
    const clean = name.trim();
    if (!clean || clean === a.name) { setAssets((xs) => xs.map((x) => (x.id === a.id ? { ...x } : x))); return; }
    setError("");
    try {
      const updated = await api<Asset>(`/api/assets/${a.id}`, { method: "PATCH", json: { name: clean } });
      setAssets((xs) => xs.map((x) => (x.id === a.id ? updated : x)));
      setSelected((s) => (s && s.id === a.id ? updated : s));
    } catch (e) { fail(e); }
  };

  const remove = async (a: Asset) => {
    if (!window.confirm(`¿Borrar «${a.name}» de la librería?`)) return;
    setError("");
    try {
      await api(`/api/assets/${a.id}`, { method: "DELETE" });
      setAssets((xs) => xs.filter((x) => x.id !== a.id));
      setSelected((s) => (s && s.id === a.id ? null : s));
    } catch (e) { fail(e); }
  };

  return (
    <div className="page"
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragging(true); } }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
      onDrop={(e) => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files.length) void upload(e.dataTransfer.files); }}>
      <div className="bar"><Link to="/">← Inicio</Link><h1>Imágenes</h1></div>
      <div className="gfx-lib">
        <label className="gfx-upload">
          <input type="file" multiple accept="image/png,image/jpeg,image/webp" disabled={uploading} onChange={(e) => { if (e.target.files?.length) void upload(e.target.files); e.target.value = ""; }} />
          {uploading ? "Subiendo…" : "+ Subir imágenes"}
        </label>
        <span className="muted hint">También puedes arrastrarlas aquí. PNG, JPG o WebP de hasta 5 MB. Elige una para editarla (quitar fondo, recortar en óvalo…).</span>
      </div>
      {dragging && <div className="img-drop">Suelta las imágenes para subirlas</div>}
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}

      <div className="img-grid">
        {assets.map((a) => (
          <div key={a.id} className={`img-card${selected?.id === a.id ? " sel" : ""}`}>
            <button className="ghost img-thumb" onClick={() => setSelected(a)} title="Editar">{a.url ? <img src={a.url} alt={a.name} /> : a.name}</button>
            <input key={a.name} className="img-name" defaultValue={a.name} maxLength={120} title="Pulsa para renombrar"
              onBlur={(e) => void rename(a, e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") { e.currentTarget.value = a.name; e.currentTarget.blur(); } }} />
            <div className="img-actions">
              <button className="ghost" onClick={() => setSelected(a)}>Editar</button>
              <button className="ghost" onClick={() => void remove(a)}>Borrar</button>
            </div>
          </div>
        ))}
        {assets.length === 0 && <p className="muted">Aún no tienes imágenes: sube alguna o genera mapas de países.</p>}
      </div>

      {selected && <Editor key={selected.id} asset={selected} onSaved={(a, replaced) => { void load(); setSelected(a); setNotice(replaced ? "Imagen reemplazada" : `Copia guardada: «${a.name}»`); }} onClose={() => setSelected(null)} onError={fail} />}

      <CountryMaps assets={assets} onAdded={(made) => setAssets((xs) => [...made, ...xs])} onError={setError} />
    </div>
  );
}

function Editor({ asset, onSaved, onClose, onError }: { asset: Asset; onSaved: (a: Asset, replaced: boolean) => void; onClose: () => void; onError: (e: unknown) => void }) {
  const [removeBg, setRemoveBg] = useState(false);
  const [flipH, setFlipH] = useState(false);
  const [flipV, setFlipV] = useState(false);
  const [rotate, setRotate] = useState(0);
  const [shape, setShape] = useState<Shape>("rect");
  const [box, setBox] = useState<Box>(FULL);
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [resultUrl, setResultUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState(`${asset.name} (editado)`);
  const [aspect, setAspect] = useState(1);           // ancho / alto de la imagen base mostrada
  const stage = useRef<HTMLDivElement>(null);
  const drag = useRef<{ mode: "move" | "size"; px: number; py: number; box: Box } | null>(null);

  // La imagen de trabajo: la original, o con fondo quitado / volteada / girada (lo calcula el servidor; el recorte no entra aquí).
  useEffect(() => {
    const ctrl = new AbortController();
    const needsServer = removeBg || flipH || flipV || rotate !== 0;
    if (!needsServer) { setBaseUrl(asset.url); return () => ctrl.abort(); }
    setLoading(true);
    const t = setTimeout(() => {
      apiBlob(`/api/assets/${asset.id}/preview`, { remove_bg: removeBg, flip_h: flipH, flip_v: flipV, rotate }, ctrl.signal)
        .then((b) => setBaseUrl((old) => { if (old && old.startsWith("blob:")) URL.revokeObjectURL(old); return URL.createObjectURL(b); }))
        .catch((e) => { if (!(e instanceof DOMException && e.name === "AbortError")) onError(e); })
        .finally(() => setLoading(false));
    }, 250);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [asset.id, asset.url, removeBg, flipH, flipV, rotate]);   // eslint-disable-line react-hooks/exhaustive-deps

  const ops = useCallback(() => ({ remove_bg: removeBg, flip_h: flipH, flip_v: flipV, rotate, shape, ...(isFull(box) ? {} : { crop: box }) }), [removeBg, flipH, flipV, rotate, shape, box]);

  // El resultado final (con recorte y forma), en pequeño.
  useEffect(() => {
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      apiBlob(`/api/assets/${asset.id}/preview`, ops(), ctrl.signal)
        .then((b) => setResultUrl((old) => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(b); }))
        .catch(() => undefined);
    }, 350);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [asset.id, ops]);

  // En círculo la caja es cuadrada (en píxeles de la imagen).
  const squareBox = useCallback((b: Box, a: number): Box => {
    const side = Math.min(b.w * a, b.h);                      // en unidades de alto
    const w = side / a, h = side;
    return { x: clamp(b.x + (b.w - w) / 2, 0, 1 - w), y: clamp(b.y + (b.h - h) / 2, 0, 1 - h), w, h };
  }, []);
  useEffect(() => { if (shape === "circle") setBox((b) => squareBox(b, aspect)); }, [shape, aspect, squareBox]);

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current, el = stage.current;
    if (!d || !el) return;
    const r = el.getBoundingClientRect();
    const dx = (e.clientX - d.px) / r.width, dy = (e.clientY - d.py) / r.height;
    if (d.mode === "move") setBox({ ...d.box, x: clamp(d.box.x + dx, 0, 1 - d.box.w), y: clamp(d.box.y + dy, 0, 1 - d.box.h) });
    else {
      let w = clamp(d.box.w + dx, 0.05, 1 - d.box.x), h = clamp(d.box.h + dy, 0.05, 1 - d.box.y);
      if (shape === "circle") { const side = Math.min(w * aspect, h, (1 - d.box.x) * aspect, 1 - d.box.y); w = side / aspect; h = side; }
      setBox({ ...d.box, w, h });
    }
  };
  const start = (mode: "move" | "size") => (e: React.PointerEvent) => {
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { mode, px: e.clientX, py: e.clientY, box };
  };

  const zoom = clamp(1 / Math.max(box.w, box.h), 1, 6);
  const setZoom = (z: number) => {
    const cx = box.x + box.w / 2, cy = box.y + box.h / 2;
    let w = 1 / z, h = 1 / z;
    if (shape === "circle") { const side = Math.min(w * aspect, h); w = side / aspect; h = side; }
    setBox({ x: clamp(cx - w / 2, 0, 1 - w), y: clamp(cy - h / 2, 0, 1 - h), w, h });
  };
  const reset = () => { setRemoveBg(false); setFlipH(false); setFlipV(false); setRotate(0); setShape("rect"); setBox(FULL); };

  const save = async (mode: "copy" | "replace") => {
    setSaving(true);
    try {
      const saved = await api<Asset>(`/api/assets/${asset.id}/edit`, { json: { ...ops(), mode, name: mode === "copy" ? name.trim() || undefined : undefined } });
      onSaved(saved, mode === "replace");
    } catch (e) { onError(e); } finally { setSaving(false); }
  };

  const round = shape !== "rect";
  return (
    <section className="img-editor">
      <div className="section-head"><h2>Editar «{asset.name}»</h2><button className="ghost" onClick={onClose}>Cerrar</button></div>
      <div className="img-editor-body">
        <div>
          <div className="img-stage checker" ref={stage} onPointerMove={onPointerMove} onPointerUp={() => { drag.current = null; }}>
            {baseUrl && <img src={baseUrl} alt="" draggable={false} onLoad={(e) => setAspect(e.currentTarget.naturalWidth / e.currentTarget.naturalHeight)} />}
            {loading && <div className="img-loading">{removeBg ? "Quitando el fondo… (la primera vez tarda unos segundos)" : "Procesando…"}</div>}
            <div className={`img-crop${round ? " round" : ""}`} style={{ left: `${box.x * 100}%`, top: `${box.y * 100}%`, width: `${box.w * 100}%`, height: `${box.h * 100}%` }} onPointerDown={start("move")}>
              <span className="img-handle" onPointerDown={start("size")} />
            </div>
          </div>
          <p className="muted hint">Arrastra el recuadro para elegir la zona y tira de la esquina para cambiar su tamaño.</p>
        </div>
        <div className="img-side">
          <div className="img-tools">
            <button className={removeBg ? "" : "ghost"} onClick={() => setRemoveBg((v) => !v)} title="Quita el fondo con IA">{removeBg ? "✔ Sin fondo" : "Quitar fondo (IA)"}</button>
            <button className={flipH ? "" : "ghost"} onClick={() => setFlipH((v) => !v)} title="Voltear horizontalmente">↔ Voltear</button>
            <button className={flipV ? "" : "ghost"} onClick={() => setFlipV((v) => !v)} title="Voltear verticalmente">↕ Voltear</button>
            <button className="ghost" onClick={() => setRotate((r) => { const n = r + 90; return n > 180 ? n - 360 : n; })}>⟳ 90°</button>
          </div>
          <label>Giro {rotate}°<input type="range" min={-180} max={180} step={1} value={rotate} onChange={(e) => setRotate(Number(e.target.value))} /></label>
          <label>Forma del recorte
            <select value={shape} onChange={(e) => setShape(e.target.value as Shape)}>
              <option value="rect">Rectángulo</option><option value="ellipse">Óvalo</option><option value="circle">Círculo</option>
            </select>
          </label>
          <label>Zoom ×{zoom.toFixed(1)}<input type="range" min={1} max={6} step={0.1} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} /></label>
          <div>
            <div className="muted">Resultado</div>
            <div className="img-result checker">{resultUrl ? <img src={resultUrl} alt="Resultado" /> : <span className="muted">…</span>}</div>
          </div>
          <label>Nombre de la copia<input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></label>
          <div className="clip-actions">
            <button disabled={saving || loading} onClick={() => void save("copy")}>{saving ? "Guardando…" : "Guardar como copia"}</button>
            <button className="ghost" disabled={saving || loading} onClick={() => void save("replace")} title="Sobrescribe esta imagen (no si ya se usa en un gráfico o plantilla)">Reemplazar</button>
            <button className="ghost" onClick={reset}>Restablecer</button>
          </div>
        </div>
      </div>
    </section>
  );
}
