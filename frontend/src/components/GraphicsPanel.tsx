import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Asset, Clip, Graphic, GraphicsPlan, Interpreted, Word } from "../types";
import { fmtTime } from "../types";

const EMOJI = /^[\p{So}\p{Sk}\p{Cf}\p{Mn}]{1,16}$/u;
const round = (n: number) => Math.round(n * 100) / 100;
const PLAN_DELAY_MS = 400;
/** Campos propios de cada motivo: al cambiar de tipo se borran todos y se pone lo del nuevo. */
const CLEAR: Partial<Graphic> = { text: undefined, emoji: undefined, target: undefined, asset_id: undefined, style: undefined, effect: undefined, entry: undefined,
  asset_ids: undefined, from_value: undefined, to_value: undefined, prefix: undefined, suffix: undefined, label: undefined, name: undefined, role: undefined };
const beatLabel = (b: Graphic, assetName?: string) =>
  b.type === "keyword" || b.type === "strike" ? `${b.type === "strike" ? "✗ " : ""}${b.text}` : b.type === "image" ? (assetName ?? "imagen")
  : b.type === "puppets" ? "🧍🧍 monigotes" : b.type === "counter" ? `${b.to_value}${b.suffix ?? ""}` : b.type === "lower_third" ? (b.name ?? "rótulo") : `${b.emoji}${b.target ? "→" + b.target : ""}`;
const PRESETS: { label: string; emoji: string; target?: string }[] = [
  { label: "🐔 → 🗳️ votar", emoji: "🐔", target: "🗳️" }, { label: "🔥", emoji: "🔥" }, { label: "💰", emoji: "💰" },
  { label: "😱", emoji: "😱" }, { label: "👀", emoji: "👀" }, { label: "🚨", emoji: "🚨" }, { label: "✅", emoji: "✅" }, { label: "❌", emoji: "❌" },
];

/** Mensaje de lo que impediría guardar los gráficos (vacío si todo está bien). */
export function graphicsProblem(list: Graphic[], duration: number): string {
  for (const g of list) {
    if (g.at < 0 || g.at > duration) return `Un gráfico (${g.at.toFixed(1)} s) queda fuera del clip`;
    if (g.type === "keyword" && !(g.text ?? "").trim()) return "Una tarjeta no tiene texto";
    if (g.type === "strike" && !(g.text ?? "").trim()) return "Un tachado no tiene texto";
    if (g.type === "counter" && (g.to_value === undefined || Number.isNaN(g.to_value))) return "Un contador no tiene cifra final";
    if (g.type === "lower_third" && !(g.name ?? "").trim()) return "Un rótulo no tiene nombre";
    if (g.type === "puppets" && !(g.asset_ids?.length)) return "Los monigotes no tienen cara";
    if (g.type === "image" && !g.asset_id) return "Un gráfico de imagen no tiene imagen";
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
  /** Palabras de la transcripción: para mostrar en qué frase cae cada gráfico. */
  words?: Word[];
};

export default function GraphicsPanel({ clip, list, onChange, start, end, layout, introEnabled, cortinillaAt, trimDirty, editable, currentTime, picked, seek, words = [] }: Props) {
  const duration = end - start;
  const [assets, setAssets] = useState<Asset[]>([]);
  const [assetError, setAssetError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [suggestNotice, setSuggestNotice] = useState("");
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [describe, setDescribe] = useState<Record<number, string>>({});
  const [understood, setUnderstood] = useState<Record<number, string>>({});
  const [plan, setPlan] = useState<GraphicsPlan | null>(null);
  const [planError, setPlanError] = useState("");
  const problem = graphicsProblem(list, duration);

  const [mapOpen, setMapOpen] = useState(false);
  const [countries, setCountries] = useState<{ name: string; group: string }[]>([]);
  const [mapPick, setMapPick] = useState<string[]>([]);
  const [addingMaps, setAddingMaps] = useState(false);
  const toggleMaps = () => {
    setMapOpen((o) => !o);
    if (countries.length === 0) api<{ name: string; group: string }[]>("/api/assets/maps/countries").then(setCountries).catch((e) => setAssetError(e instanceof Error ? e.message : String(e)));
  };
  const addMaps = async () => {
    setAssetError(""); setAddingMaps(true);
    try {
      const made = await api<Asset[]>("/api/assets/maps", { json: { countries: mapPick } });
      setAssets((xs) => [...made, ...xs]); setMapPick([]);
    } catch (e) { setAssetError(e instanceof Error ? e.message : String(e)); } finally { setAddingMaps(false); }
  };
  const loadAssets = () => api<Asset[]>("/api/assets").then(setAssets).catch((e) => setAssetError(e instanceof Error ? e.message : String(e)));
  useEffect(() => { loadAssets(); }, []);
  const assetOf = (id?: number) => assets.find((a) => a.id === id);
  const upload = async (file: File | undefined) => {
    if (!file) return;
    setAssetError(""); setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const a = await api<Asset>("/api/assets", { method: "POST", body: fd });
      setAssets((xs) => [a, ...xs]);
    } catch (e) { setAssetError(e instanceof Error ? e.message : String(e)); } finally { setUploading(false); }
  };
  // Frase libre → entrada, efecto y estilo (palabras clave o modelo); se aplica a la fila y se enseña lo entendido para corregirlo.
  const interpret = async (i: number) => {
    const text = (describe[i] ?? "").trim();
    if (!text) return;
    try {
      const r = await api<Interpreted>("/api/graphics/interpret", { json: { text } });
      const patch: Partial<Graphic> = {};
      if (r.entry) patch.entry = r.entry;
      if (r.effect) patch.effect = r.effect;
      if (r.style) patch.style = r.style;
      if (Object.keys(patch).length) update(i, patch);
      setUnderstood((u) => ({ ...u, [i]: r.source === "none" ? "No he entendido la frase: usa los selectores (por ejemplo «golpe», «explota», «se vaporiza», «cae»)." : `Entendido (${r.source === "llm" ? "con el modelo" : "por palabras"}): ${r.understood}. Corrígelo en los selectores si no es lo que querías.` }));
    } catch (e) { setUnderstood((u) => ({ ...u, [i]: e instanceof Error ? e.message : String(e) })); }
  };
  // El planificador propone gráficos desde la transcripción (modelo o plan básico); se añaden a los que ya hay, que mandan.
  const suggest = async () => {
    setSuggesting(true); setSuggestNotice(""); setAssetError("");
    try {
      const r = await api<{ beats: (Graphic & { reason?: string })[]; source: string; notes: string[]; max_beats: number }>(`/api/clips/${clip.id}/graphics-plan/suggest`, {
        json: { graphics: list, start, end, layout, intro_enabled: introEnabled, cortinilla_at: cortinillaAt },
      });
      const found: Record<string, string> = {};
      const added = r.beats.map(({ reason, ...g }) => { found[`${g.type}:${g.at}`] = reason ?? ""; return g as Graphic; });
      if (added.length) onChange(sorted([...list, ...added]));
      setReasons((x) => ({ ...x, ...found }));
      setSuggestNotice(
        added.length === 0
          ? `No hay propuestas nuevas que quepan. ${r.notes.join(" ")}`
          : `${added.length} gráfico${added.length !== 1 ? "s" : ""} propuesto${added.length !== 1 ? "s" : ""} ${r.source === "model" ? "por el modelo" : "(propuesta básica, sin modelo)"}. Revísalos, cámbialos o quítalos y guarda. ${r.notes.join(" ")}`,
      );
    } catch (e) { setSuggestNotice(e instanceof Error ? e.message : String(e)); } finally { setSuggesting(false); }
  };
  const removeAsset = async (a: Asset) => {
    if (!window.confirm(`¿Borrar la imagen «${a.name}» de la librería?`)) return;
    setAssetError("");
    try { await api(`/api/assets/${a.id}`, { method: "DELETE" }); setAssets((xs) => xs.filter((x) => x.id !== a.id)); }
    catch (e) { setAssetError(e instanceof Error ? e.message : String(e)); }
  };

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
  // Los gráficos se listan por orden de aparición y con un número que también sale en la línea de tiempo.
  const order = list.map((_, i) => i).sort((a, b) => list[a].at - list[b].at || a - b);
  const numberOf = (type: string, at: number) => { const k = order.findIndex((i) => list[i].type === type && list[i].at === at); return k >= 0 ? k + 1 : null; };
  /** La frase donde cae el gráfico: unas palabras antes y después, con la palabra ancla resaltada. */
  const phraseAt = (at: number) => {
    const abs = start + at;
    let k = -1, best = Infinity;
    words.forEach((w, j) => { const d = Math.abs(w.start - abs); if (d < best) { best = d; k = j; } });
    if (k < 0 || best > 1.5) return null;
    const lo = Math.max(0, k - 6), hi = Math.min(words.length, k + 9);
    return { before: words.slice(lo, k).map((w) => w.text).join(" "), word: words[k].text, after: words.slice(k + 1, hi).map((w) => w.text).join(" "), lead: lo > 0, tail: hi < words.length };
  };
  const rows = useMemo(() => ({ keyword: 0, counter: 0, strike: 0, image: 1, lower_third: 1, puppets: 1, emoji: 2 } as const), []);

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
          <div key={`b${i}`} className={`gfx-beat ${b.type}`} style={{ left: pct(b.start), width: `calc(${pct(b.end)} - ${pct(b.start)})`, top: 8 + rows[b.type] * 18 }}
            title={`${beatLabel(b, assetOf(b.asset_id)?.name)} · ${b.start.toFixed(1)}–${b.end.toFixed(1)} s`}>
            {numberOf(b.type, b.at) ?? "?"} · {beatLabel(b, assetOf(b.asset_id)?.name)}
          </div>
        ))}
        {plan?.dropped.map((d, i) => <div key={`d${i}`} className="gfx-drop" style={{ left: pct(d.beat.at) }} title={`Descartado: ${d.reason}`} />)}
        <div className="gfx-head" style={{ left: pct(nowAt) }} />
      </div>
      {suggestNotice && <p className="notice">{suggestNotice}</p>}
      <div className="muted gfx-scale"><span>0 s</span><span>{fmtTime(duration)}</span></div>

      <div className="gfx-add">
        <button disabled={!editable || suggesting || !!problem || trimDirty} title={trimDirty ? "Guarda antes el recorte" : "Propone gráficos desde la transcripción"} onClick={suggest}>
          {suggesting ? "Pensando…" : "✨ Sugerir gráficos con IA"}
        </button>
        <button disabled={!editable || !!problem} onClick={() => addAt({ type: "keyword", text: (picked?.text ?? "Palabra").replace(/[^\p{L}\p{N} ]/gu, "").toUpperCase() || "PALABRA" }, where)}>
          + Tarjeta en {whereLabel}
        </button>
        <button className="ghost" disabled={!editable || !!problem} title="Cifra que rueda hasta la palabra" onClick={() => addAt({ type: "counter", from_value: 0, to_value: Number((picked?.text ?? "").replace(/[^\d,.]/g, "").replace(",", ".")) || 100 }, where)}>+ Contador</button>
        <button className="ghost" disabled={!editable || !!problem} title="Tacha la palabra con un aspa" onClick={() => addAt({ type: "strike", text: (picked?.text ?? "Palabra").replace(/[^\p{L}\p{N} ]/gu, "").toUpperCase() || "PALABRA" }, where)}>+ Tachar</button>
        <button className="ghost" disabled={!editable || !!problem || assets.length === 0} title="Dos monigotes de comic de la mano con las caras de tu librería"
          onClick={() => addAt({ type: "puppets", asset_ids: assets.slice(0, 2).map((a) => a.id) }, where)}>+ Monigotes</button>
        <button className="ghost" disabled={!editable || !!problem} title="Rótulo de nombre y cargo" onClick={() => addAt({ type: "lower_third", name: "Nombre", role: "" }, where)}>+ Rótulo</button>
        {PRESETS.map((p) => (
          <button key={p.label} className="ghost" disabled={!editable} title={`Emoji en ${whereLabel}`} onClick={() => addAt({ type: "emoji", emoji: p.emoji, target: p.target }, where)}>{p.label}</button>
        ))}
      </div>

      <div className="gfx-lib">
        <strong>Mis imágenes</strong>
        <label className="gfx-upload">
          <input type="file" accept="image/png,image/jpeg,image/webp" disabled={uploading} onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} />
          {uploading ? "Subiendo…" : "+ Subir imagen"}
        </label>
        <span className="muted hint">PNG con fondo transparente queda mejor (hucha, logo…). Solo se usan las imágenes que subes tú.</span>
      </div>
      <div className="gfx-lib">
        <button className="ghost" onClick={toggleMaps}>{mapOpen ? "▾" : "▸"} Mapas de países</button>
        <span className="muted hint">Genera el mapa de un país (rojo, con los vecinos tenues) y úsalo como una imagen más o como objeto que orbita en la cortinilla.</span>
      </div>
      {mapOpen && (
        <div className="gfx-maps">
          {["Europa", "Otros"].map((group) => (
            <div key={group}>
              <div className="gfx-maps-head">
                <strong>{group}</strong>
                <button className="ghost" onClick={() => { const names = countries.filter((c) => c.group === group && c.name !== "Europa").map((c) => c.name); setMapPick((p) => [...new Set([...p, ...names])]); }}>Marcar todos</button>
              </div>
              <div className="gfx-maps-chips">
                {countries.filter((c) => c.group === group).map((c) => {
                  const have = assets.some((a) => a.kind === "map" && a.name === `Mapa de ${c.name}`);
                  return (
                    <label key={c.name} className={`check gfx-chip${have ? " have" : ""}`}>
                      <input type="checkbox" disabled={have} checked={have || mapPick.includes(c.name)}
                        onChange={(e) => setMapPick((p) => e.target.checked ? [...p, c.name] : p.filter((n) => n !== c.name))} />
                      {c.name}
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
          <button disabled={mapPick.length === 0 || addingMaps} onClick={addMaps}>{addingMaps ? "Generando…" : `Añadir ${mapPick.length} mapa${mapPick.length === 1 ? "" : "s"}`}</button>
        </div>
      )}
      {assetError && <p className="error">{assetError}</p>}
      {assets.length > 0 && (
        <div className="gfx-assets">
          {assets.map((a) => (
            <div key={a.id} className="gfx-asset">
              <button className="ghost" disabled={!editable || !!problem} title={`Añadir «${a.name}» en ${whereLabel}`} onClick={() => addAt({ type: "image", asset_id: a.id, style: "original", effect: "pop" }, where)}>
                {a.url ? <img src={a.url} alt={a.name} /> : a.name}
                <span>{a.name}</span>
              </button>
              <button className="ghost gfx-del" title="Borrar de la librería" onClick={() => removeAsset(a)}>✕</button>
            </div>
          ))}
        </div>
      )}

      {list.length === 0 && <p className="muted">Aún no hay gráficos en este clip.</p>}
      <ul className="gfx-list">
        {order.map((i, n) => {
          const g = list[i];
          const st = statusOf(g);
          const ph = phraseAt(g.at);
          const bad = g.type === "emoji" && (!EMOJI.test(g.emoji ?? "") || (g.target && !EMOJI.test(g.target)));
          return (
            <li key={i}>
              <div className="gfx-phrase" onClick={() => seek(start + g.at)} title="Ir a ese punto del vídeo">
                <span className="gfx-num">{n + 1}</span>
                <span className="gfx-time">{g.at.toFixed(1)} s</span>
                {ph ? <span>{ph.lead && "… "}{ph.before} <mark>{ph.word}</mark> {ph.after}{ph.tail && " …"}</span> : <span className="muted">(sin transcripción en ese punto)</span>}
              </div>
              <select value={g.type} disabled={!editable} onChange={(e) => {
                const t = e.target.value;
                if (t === "emoji") update(i, { type: "emoji", emoji: "🔥", text: undefined, asset_id: undefined, style: undefined, effect: "pop" });
                else if (t === "image") update(i, { type: "image", asset_id: assets[0]?.id, style: "original", effect: "pop", entry: "pop", text: undefined, emoji: undefined, target: undefined });
                else if (t === "counter") update(i, { ...CLEAR, type: "counter", from_value: 0, to_value: 100, suffix: "" });
                else if (t === "strike") update(i, { ...CLEAR, type: "strike", text: "PALABRA" });
                else if (t === "puppets") update(i, { ...CLEAR, type: "puppets", asset_ids: assets.slice(0, 2).map((a) => a.id) });
                else if (t === "lower_third") update(i, { ...CLEAR, type: "lower_third", name: "Nombre", role: "" });
                else update(i, { ...CLEAR, type: "keyword", text: "PALABRA" });
              }}>
                <option value="keyword">Tarjeta</option>
                <option value="counter">Contador</option>
                <option value="strike">Tachado</option>
                <option value="lower_third">Rótulo nombre</option>
                <option value="puppets" disabled={assets.length === 0}>Monigotes de la mano</option>
                <option value="emoji">Emoji</option>
                <option value="image" disabled={assets.length === 0}>Imagen</option>
              </select>
              <label className="gfx-at">a los
                <input type="number" min={0} max={duration} step={0.1} value={g.at} disabled={!editable} onChange={(e) => update(i, { at: round(Number(e.target.value)) })} /> s
              </label>
              <button className="ghost" disabled={!editable} title="Poner en el instante actual del vídeo" onClick={() => update(i, { at: round(Math.min(Math.max(0, nowAt), duration)) })}>Aquí</button>
              <button className="ghost" title="Ir a ese punto" onClick={() => seek(start + g.at)}>Ver</button>
              {g.type === "image" ? (
                <>
                  <select value={g.asset_id ?? ""} disabled={!editable} onChange={(e) => update(i, { asset_id: Number(e.target.value) })} title="Imagen">
                    {assets.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                  </select>
                  <select value={g.style ?? "original"} disabled={!editable} onChange={(e) => update(i, { style: e.target.value as Graphic["style"] })} title="Estilo">
                    <option value="original">Tal cual</option>
                    <option value="card">Tarjeta de papel</option>
                    <option value="silhouette">Silueta</option>
                    <option value="red">Rojo de marca</option>
                  </select>
                  <select value={g.entry ?? "pop"} disabled={!editable} onChange={(e) => update(i, { entry: e.target.value as Graphic["entry"] })} title="Cómo entra">
                    <option value="pop">Aparece con rebote</option>
                    <option value="punch">Entra de un golpe</option>
                    <option value="drop">Cae desde arriba</option>
                    <option value="slide_left">Desde la izquierda</option>
                    <option value="slide_right">Desde la derecha</option>
                    <option value="slide_top">Baja desde arriba</option>
                  </select>
                  <select value={g.effect ?? "pop"} disabled={!editable} onChange={(e) => update(i, { effect: e.target.value as Graphic["effect"] })} title="Qué pasa en la palabra">
                    <option value="pop">Se queda y sale</option>
                    <option value="vaporize">Se vaporiza</option>
                    <option value="break">Se parte</option>
                    <option value="explode">Explota</option>
                  </select>
                </>
              ) : g.type === "keyword" || g.type === "strike" ? (
                <input className="gfx-text" value={g.text ?? ""} maxLength={40} disabled={!editable} onChange={(e) => update(i, { text: e.target.value })} placeholder={g.type === "strike" ? "TEXTO A TACHAR" : "TEXTO"} />
              ) : g.type === "counter" ? (
                <>
                  <label className="gfx-at">de <input type="number" step="any" value={g.from_value ?? 0} disabled={!editable} onChange={(e) => update(i, { from_value: Number(e.target.value) })} /></label>
                  <label className="gfx-at">a <input type="number" step="any" value={g.to_value ?? ""} disabled={!editable} onChange={(e) => update(i, { to_value: e.target.value === "" ? undefined : Number(e.target.value) })} /></label>
                  <input className="gfx-short" value={g.prefix ?? ""} maxLength={8} disabled={!editable} onChange={(e) => update(i, { prefix: e.target.value || undefined })} placeholder="prefijo" title="Antes de la cifra (ej. $)" />
                  <input className="gfx-short" value={g.suffix ?? ""} maxLength={12} disabled={!editable} onChange={(e) => update(i, { suffix: e.target.value || undefined })} placeholder="unidad" title="Después de la cifra (ej. ' M€', ' %')" />
                  <input className="gfx-text" value={g.label ?? ""} maxLength={40} disabled={!editable} onChange={(e) => update(i, { label: e.target.value || undefined })} placeholder="etiqueta (opcional)" />
                </>
              ) : g.type === "puppets" ? (
                <>
                  {[0, 1, 2].filter((k) => k < Math.max(1, (g.asset_ids?.length ?? 0)) + (k === (g.asset_ids?.length ?? 0) && (g.asset_ids?.length ?? 0) < 3 ? 1 : 0)).map((k) => (
                    <select key={k} value={g.asset_ids?.[k] ?? ""} disabled={!editable} title={`Cara del monigote ${k + 1}`}
                      onChange={(e) => {
                        const ids = [...(g.asset_ids ?? [])];
                        if (e.target.value === "") ids.splice(k, 1); else ids[k] = Number(e.target.value);
                        update(i, { asset_ids: ids });
                      }}>
                      <option value="">{k === 0 ? "Elige una cara" : "(quitar / añadir otro)"}</option>
                      {assets.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                    </select>
                  ))}
                </>
              ) : g.type === "lower_third" ? (
                <>
                  <input className="gfx-text" value={g.name ?? ""} maxLength={40} disabled={!editable} onChange={(e) => update(i, { name: e.target.value })} placeholder="Nombre" />
                  <input className="gfx-text" value={g.role ?? ""} maxLength={60} disabled={!editable} onChange={(e) => update(i, { role: e.target.value || undefined })} placeholder="Cargo (opcional)" />
                </>
              ) : (
                <>
                  <input className={`gfx-emoji${bad ? " invalid" : ""}`} value={g.emoji ?? ""} maxLength={16} disabled={!editable} onChange={(e) => update(i, { emoji: e.target.value })} title="Emoji" />
                  <span className="muted">→</span>
                  {!g.target && (
                    <select value={g.effect ?? "pop"} disabled={!editable} onChange={(e) => update(i, { effect: e.target.value as Graphic["effect"] })} title="Efecto en la palabra">
                      <option value="pop">Entra y sale</option>
                      <option value="vaporize">Se vaporiza</option>
                      <option value="explode">Explota</option>
                    </select>
                  )}
                  <input className={`gfx-emoji${bad ? " invalid" : ""}`} value={g.target ?? ""} maxLength={16} disabled={!editable} onChange={(e) => update(i, { target: e.target.value || undefined })} placeholder="objetivo" title="Objeto al que llega (opcional)" />
                </>
              )}
              <button className="ghost" disabled={!editable} onClick={() => remove(i)} title="Quitar">✕</button>
              {g.type === "image" && editable && (
                <span className="gfx-describe">
                  <input value={describe[i] ?? ""} maxLength={300} placeholder="o descríbelo: el guante da un golpe y explota"
                    onChange={(e) => setDescribe((d) => ({ ...d, [i]: e.target.value }))} onKeyDown={(e) => { if (e.key === "Enter") interpret(i); }} />
                  <button className="ghost" disabled={!(describe[i] ?? "").trim()} onClick={() => interpret(i)}>Entender</button>
                </span>
              )}
              {understood[i] && <span className="muted gfx-understood">{understood[i]}</span>}
              {reasons[`${g.type}:${g.at}`] && <span className="muted">✨ {reasons[`${g.type}:${g.at}`]}</span>}
              {st.text && <span className={st.ok ? "muted" : "error"}>{st.text}</span>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
