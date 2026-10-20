import { useState } from "react";
import { api } from "../api";
import type { Clip, ScreenRange } from "../types";
import { fmtTime } from "../types";

type Props = {
  clip: Clip;
  ranges: ScreenRange[];
  onChange: (ranges: ScreenRange[]) => void;
  start: number; end: number;
  trimDirty: boolean;
  editable: boolean;
  /** Segundo del vídeo original en el que está el reproductor. */
  currentTime: number;
  seek: (sourceSeconds: number) => void;
};

const round = (n: number) => Math.round(n * 100) / 100;
const pct = (v: number) => Math.round(v * 100);
const FULL = { x: 0, y: 0, w: 1, h: 1 };

/** Tramos en los que el vídeo original enseña una pantalla (un tuit, una web): en el render, la parte de arriba la muestra entera
 * (la región elegida ajustada al ancho) en vez del recorte del hablante. */
export default function ScreensPanel({ clip, ranges, onChange, start, end, trimDirty, editable, currentTime, seek }: Props) {
  const [detecting, setDetecting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const detect = async () => {
    setError(""); setNotice(""); setDetecting(true);
    try {
      const r = await api<{ ranges: ScreenRange[] }>(`/api/clips/${clip.id}/screens/detect`, { json: { start, end } });
      onChange(r.ranges);
      setNotice(r.ranges.length ? `Encontrados ${r.ranges.length} tramo${r.ranges.length > 1 ? "s" : ""}: revísalos y guarda los cambios.` : "No se ha encontrado ninguna pantalla compartida en este recorte.");
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setDetecting(false); }
  };
  const update = (i: number, patch: Partial<ScreenRange>) => onChange(ranges.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  const add = () => {
    const a = Math.min(Math.max(start, currentTime), end - 1);
    onChange([...ranges, { start: round(a), end: round(Math.min(end, a + 5)), ...FULL }].sort((p, q) => p.start - q.start));
  };
  const bad = (r: ScreenRange) => r.end <= r.start || r.x + r.w > 1.001 || r.y + r.h > 1.001;

  return (
    <section className="gfx-panel">
      <h2>Pantallas compartidas (tuits, webs)</h2>
      <p className="muted hint">
        Cuando el original enseña una pantalla —un tuit, una web— el recorte vertical del hablante la corta y no se lee. En estos tramos la parte
        de arriba muestra la región elegida entera, ajustada al ancho. «Detectar» busca las páginas claras con texto; puedes ajustar o añadir a mano.
      </p>
      {trimDirty && <p className="muted hint">Has cambiado el recorte sin guardar: guárdalo antes de detectar.</p>}
      <div className="gfx-add">
        <button disabled={!editable || detecting || trimDirty} onClick={detect}>{detecting ? "Buscando…" : "🔎 Detectar pantallas compartidas"}</button>
        <button className="ghost" disabled={!editable} onClick={add} title="Añade un tramo de 5 s desde el instante actual, con el cuadro entero">+ Tramo en el instante actual</button>
      </div>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {ranges.length === 0 && <p className="muted">Sin tramos: el clip usa siempre el recorte del hablante.</p>}
      <ul className="gfx-list">
        {ranges.map((r, i) => (
          <li key={i}>
            <div className="gfx-phrase" onClick={() => seek(r.start)} title="Ir al inicio del tramo">
              <span className="gfx-num">{i + 1}</span>
              <span className="gfx-time">{fmtTime(r.start)} – {fmtTime(r.end)} · {round(r.end - r.start)} s</span>
            </div>
            <label className="gfx-at">de <input type="number" step={0.1} min={0} value={r.start} disabled={!editable} onChange={(e) => update(i, { start: round(Number(e.target.value)) })} /> s</label>
            <button className="ghost" disabled={!editable} onClick={() => update(i, { start: round(currentTime) })} title="Poner el inicio en el instante actual">Aquí</button>
            <label className="gfx-at">a <input type="number" step={0.1} min={0} value={r.end} disabled={!editable} onChange={(e) => update(i, { end: round(Number(e.target.value)) })} /> s</label>
            <button className="ghost" disabled={!editable} onClick={() => update(i, { end: round(currentTime) })} title="Poner el fin en el instante actual">Aquí</button>
            <button className="ghost" onClick={() => seek(r.start)}>Ver</button>
            <div className="scr-box" title="Región que se enseña (en azul) dentro del cuadro">
              <div style={{ left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` }} />
            </div>
            <label className="gfx-at">x <input type="number" min={0} max={95} value={pct(r.x)} disabled={!editable} onChange={(e) => update(i, { x: Number(e.target.value) / 100 })} />%</label>
            <label className="gfx-at">y <input type="number" min={0} max={95} value={pct(r.y)} disabled={!editable} onChange={(e) => update(i, { y: Number(e.target.value) / 100 })} />%</label>
            <label className="gfx-at">ancho <input type="number" min={5} max={100} value={pct(r.w)} disabled={!editable} onChange={(e) => update(i, { w: Number(e.target.value) / 100 })} />%</label>
            <label className="gfx-at">alto <input type="number" min={5} max={100} value={pct(r.h)} disabled={!editable} onChange={(e) => update(i, { h: Number(e.target.value) / 100 })} />%</label>
            <button className="ghost" disabled={!editable} onClick={() => update(i, FULL)} title="Cuadro entero">Todo</button>
            <button className="ghost" disabled={!editable} onClick={() => onChange(ranges.filter((_, k) => k !== i))} title="Quitar">✕</button>
            {bad(r) && <span className="error">El fin debe ser posterior al inicio y la región no puede salirse del cuadro</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
