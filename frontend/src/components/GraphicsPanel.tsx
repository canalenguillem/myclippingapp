import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Clip, Graphic, GraphicsPlan } from "../types";
import { fmtTime } from "../types";

const EMOJI = /^[\p{So}\p{Sk}\p{Cf}\p{Mn}]{1,16}$/u;
const round = (n: number) => Math.round(n * 100) / 100;
const PLAN_DELAY_MS = 400;
const PRESETS: { label: string; emoji: string; target?: string }[] = [
  { label: "🐔 → 🗳️ votar", emoji: "🐔", target: "🗳️" }, { label: "🔥", emoji: "🔥" }, { label: "💰", emoji: "💰" },
  { label: "😱", emoji: "😱" }, { label: "👀", emoji: "👀" }, { label: "🚨", emoji: "🚨" }, { label: "✅", emoji: "✅" }, { label: "❌", emoji: "❌" },
];

/** Mensaje de lo que impediría guardar los gráficos (vacío si todo está bien). */
export function graphicsProblem(list: Graphic[], duration: number): string {
  for (const g of list) {
    if (g.at < 0 || g.at > duration) return `Un gráfico (${g.at.toFixed(1)} s) queda fuera del clip`;
    if (g.type === "keyword" && !(g.text ?? "").trim()) return "Una tarjeta no tiene texto";
    if (g.type === "emoji" && !EMOJI.test(g.emoji ?? "")) return "Un emoji no es válido (solo emojis, sin letras)";
    if (g.type === "emoji" && g.target && !EMOJI.test(g.target)) return "El objetivo de un emoji no es válido";
  }
  return list.length > 40 ? "Máximo 40 gráficos" : "";
}

type Props = {
  clip: Clip;
  list: Graphic[];
  onChange: (list: Graphic[]) => void;
  start: number; end: number; layout: Clip["layout"]; introEnabled: boolean; cortinillaAt: number | null;
  trimDirty: boolean;
  editable: boolean;
  /** Segundo del vídeo fuente en el que está el reproductor. */
  currentTime: number;
  /** Palabra elegida en la transcripción (inicio absoluto y texto), si hay. */
  picked: { start: number; text: string } | null;
  seek: (sourceSeconds: number) => void;
};

export default function GraphicsPanel({ clip, list, onChange, start, end, layout, introEnabled, cortinillaAt, trimDirty, editable, currentTime, picked, seek }: Props) {
  const duration = end - start;
  const [plan, setPlan] = useState<GraphicsPlan | null>(null);
  const [planError, setPlanError] = useState("");
  const problem = graphicsProblem(list, duration);

  // El plan real (ventanas, descartados) se pide al backend sobre lo que hay en el formulario, guardado o no.
  useEffect(() => {
    if (problem || duration < 1) { setPlan(null); return; }
    const timer = setTimeout(() => {
      api<GraphicsPlan>(`/api/clips/${clip.id}/graphics-plan`, {
        json: { graphics: list, start, end, layout, intro_enabled: introEnabled, cortinilla_at: cortinillaAt },
      }).then((p) => { setPlan(p); setPlanError(""); }).catch((e) => setPlanError(e instanceof Error ? e.message : String(e)));
    }, PLAN_DELAY_MS);
    return () => clearTimeout(timer);
  }, [clip.id, list, start, end, layout, introEnabled, cortinillaAt, problem, duration]);

  const sorted = (xs: Graphic[]) => [...xs].sort((a, b) => a.at - b.at);
  const update = (i: number, patch: Partial<Graphic>) => onChange(sorted(list.map((g, k) => (k === i ? { ...g, ...patch } : g))));
  const remove = (i: number) => onChange(list.filter((_, k) => k !== i));
  const addAt = (g: Omit<Graphic, "at">, at: number) => onChange(sorted([...list, { ...g, at: round(Math.min(Math.max(0, at), duration)) }]));
  const nowAt = currentTime - start;
  const wordAt = picked ? picked.start - start : null;
  const where = wordAt !== null && wordAt >= 0 && wordAt <= duration ? wordAt : nowAt;
  const whereLabel = wordAt !== null && wordAt >= 0 && wordAt <= duration ? `«${picked?.text}»` : "el instante actual";

  const statusOf = (g: Graphic) => {
    const kept = plan?.beats.find((b) => b.type === g.type && b.at === g.at);
    if (kept) return { ok: true, text: `visible de ${kept.start.toFixed(1)} a ${kept.end.toFixed(1)} s` };
    const lost = plan?.dropped.find((d) => d.beat.type === g.type && d.beat.at === g.at);
    return lost ? { ok: false, text: `no entra: ${lost.reason}` } : { ok: true, text: "" };
  };
  const pct = (s: number) => `${(Math.min(Math.max(s, 0), duration) / duration) * 100}%`;
  const rows = useMemo(() => ({ keyword: 0, emoji: 1 } as const), []);

  return (
    <section className="gfx-panel">
      <h2>Gráficos</h2>
      <p className="muted hint">
        Cada gráfico se ancla al inicio de una palabra: entra un poco antes y la acción cae en ella. Elige una palabra en la transcripción o
        coloca el vídeo y añade un gráfico ahí. Dos tarjetas nunca van a la vez{layout === "full" ? "; en pantalla completa, ningún gráfico con otro" : ""}.
      </p>
      {trimDirty && <p className="muted hint">Has cambiado el recorte sin guardar: guarda antes de colocar gráficos para que sigan pegados a su palabra.</p>}
      {problem && <p className="error">{problem}</p>}
      {planError && <p className="error">{planError}</p>}

      <div className="gfx-timeline" onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); seek(start + ((e.clientX - r.left) / r.width) * duration); }}>
        {plan && <div className="gfx-hook" style={{ left: 0, width: pct(plan.hook_seconds) }} title="Gancho"><span>gancho</span></div>}
        {plan?.cortinilla_at != null && <div className="gfx-cort" style={{ left: pct(plan.cortinilla_at) }} title={`Cortinilla de inicio a ${plan.cortinilla_at.toFixed(1)} s`} />}
        {plan?.beats.map((b, i) => (
          <div key={`b${i}`} className={`gfx-beat ${b.type}`} style={{ left: pct(b.start), width: `calc(${pct(b.end)} - ${pct(b.start)})`, top: 8 + rows[b.type] * 22 }}
            title={`${b.type === "keyword" ? b.text : b.emoji} · ${b.start.toFixed(1)}–${b.end.toFixed(1)} s`}>
            {b.type === "keyword" ? b.text : `${b.emoji}${b.target ? "→" + b.target : ""}`}
          </div>
        ))}
        {plan?.dropped.map((d, i) => <div key={`d${i}`} className="gfx-drop" style={{ left: pct(d.beat.at) }} title={`Descartado: ${d.reason}`} />)}
        <div className="gfx-head" style={{ left: pct(nowAt) }} />
      </div>
      <div className="muted gfx-scale"><span>0 s</span><span>{fmtTime(duration)}</span></div>

      <div className="gfx-add">
        <button disabled={!editable || !!problem} onClick={() => addAt({ type: "keyword", text: (picked?.text ?? "Palabra").replace(/[^\p{L}\p{N} ]/gu, "").toUpperCase() || "PALABRA" }, where)}>
          + Tarjeta en {whereLabel}
        </button>
        {PRESETS.map((p) => (
          <button key={p.label} className="ghost" disabled={!editable} title={`Emoji en ${whereLabel}`} onClick={() => addAt({ type: "emoji", emoji: p.emoji, target: p.target }, where)}>{p.label}</button>
        ))}
      </div>

      {list.length === 0 && <p className="muted">Aún no hay gráficos en este clip.</p>}
      <ul className="gfx-list">
        {list.map((g, i) => {
          const st = statusOf(g);
          const bad = g.type === "emoji" && (!EMOJI.test(g.emoji ?? "") || (g.target && !EMOJI.test(g.target)));
          return (
            <li key={i}>
              <select value={g.type} disabled={!editable} onChange={(e) => update(i, e.target.value === "emoji" ? { type: "emoji", emoji: "🔥", text: undefined } : { type: "keyword", text: "PALABRA", emoji: undefined, target: undefined })}>
                <option value="keyword">Tarjeta</option>
                <option value="emoji">Emoji</option>
              </select>
              <label className="gfx-at">a los
                <input type="number" min={0} max={duration} step={0.1} value={g.at} disabled={!editable} onChange={(e) => update(i, { at: round(Number(e.target.value)) })} /> s
              </label>
              <button className="ghost" disabled={!editable} title="Poner en el instante actual del vídeo" onClick={() => update(i, { at: round(Math.min(Math.max(0, nowAt), duration)) })}>Aquí</button>
              <button className="ghost" title="Ir a ese punto" onClick={() => seek(start + g.at)}>Ver</button>
              {g.type === "keyword" ? (
                <input className="gfx-text" value={g.text ?? ""} maxLength={40} disabled={!editable} onChange={(e) => update(i, { text: e.target.value })} placeholder="TEXTO" />
              ) : (
                <>
                  <input className={`gfx-emoji${bad ? " invalid" : ""}`} value={g.emoji ?? ""} maxLength={16} disabled={!editable} onChange={(e) => update(i, { emoji: e.target.value })} title="Emoji" />
                  <span className="muted">→</span>
                  <input className={`gfx-emoji${bad ? " invalid" : ""}`} value={g.target ?? ""} maxLength={16} disabled={!editable} onChange={(e) => update(i, { target: e.target.value || undefined })} placeholder="objetivo" title="Objeto al que llega (opcional)" />
                </>
              )}
              <button className="ghost" disabled={!editable} onClick={() => remove(i)} title="Quitar">✕</button>
              {st.text && <span className={st.ok ? "muted" : "error"}>{st.text}</span>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
