import { useEffect, useState } from "react";
import { api } from "../api";
import type { CaptionStyle, KnownSpeaker, Speaker } from "../types";
import { speakerColor } from "../types";

type Props = { speakers: Record<string, Speaker>; onSave: (s: Record<string, Speaker>) => Promise<void>; projectId?: number; speakingNow?: string | null };

export default function SpeakerPanel({ speakers, onSave, projectId, speakingNow }: Props) {
  const [known, setKnown] = useState<KnownSpeaker[]>([]);
  useEffect(() => {
    api<KnownSpeaker[]>(`/api/speakers/known${projectId ? `?exclude_project=${projectId}` : ""}`).then(setKnown).catch(() => setKnown([]));
  }, [projectId]);
  const [draft, setDraft] = useState(speakers);
  const [saving, setSaving] = useState(false);
  // El padre consulta el proyecto cada pocos segundos y cada respuesta es un objeto nuevo: reiniciar el borrador
  // por identidad borraba lo que el usuario estaba escribiendo. Solo se reinicia si el CONTENIDO cambia.
  const serverState = JSON.stringify(speakers);
  useEffect(() => setDraft(JSON.parse(serverState)), [serverState]);

  const labels = Object.keys(draft).sort();
  const dirty = JSON.stringify(draft) !== JSON.stringify(speakers);
  const set = (label: string, patch: Partial<Speaker>) => setDraft((d) => ({ ...d, [label]: { ...d[label], ...patch } }));

  // Rellena nombre, cargo, estilo y «clip citado» con alguien que ya has usado en otro vídeo.
  const useKnown = (label: string, k: KnownSpeaker) => set(label, { name: k.name, role: k.role, caption_style: k.caption_style, is_source: k.is_source });
  const byName = (name: string) => known.find((k) => k.name.toLowerCase() === name.trim().toLowerCase());
  const taken = new Set(Object.values(draft).map((c) => c.name.trim().toLowerCase()).filter(Boolean));

  const addSpeaker = () => {
    const next = "ABCDEFGH".split("").find((l) => !(l in draft));
    if (next) setDraft((d) => ({ ...d, [next]: { name: "", role: "", caption_style: "sans_upper", is_source: false, focus_x: 0.5 } }));
  };

  if (labels.length === 0) return <p className="muted">Sin speakers todavía.</p>;
  return (
    <div className="speakers">
      <datalist id="known-speaker-names">{known.map((k) => <option key={k.name} value={k.name}>{k.role}</option>)}</datalist>
      {labels.map((label) => (
        <div className={`speaker-card${speakingNow === label ? " speaking" : ""}`} key={label} style={{ borderLeftColor: speakerColor(label, labels) }}>
          <strong>Speaker {label}{speakingNow === label ? " 🔊 habla ahora" : ""}</strong>
          {known.length > 0 && (
            <select value="" onChange={(e) => { const k = known.find((x) => x.name === e.target.value); if (k) useKnown(label, k); }} title="Rellena nombre, cargo y estilo con alguien de tus otros vídeos">
              <option value="">Elegir de mis otros vídeos…</option>
              {known.filter((k) => !taken.has(k.name.toLowerCase()) || k.name.toLowerCase() === draft[label].name.trim().toLowerCase())
                .map((k) => <option key={k.name} value={k.name}>{k.name}{k.role ? ` — ${k.role}` : ""} ({k.uses} {k.uses === 1 ? "vídeo" : "vídeos"})</option>)}
            </select>
          )}
          <input placeholder="Nombre" list="known-speaker-names" value={draft[label].name} maxLength={80}
            onChange={(e) => {
              const name = e.target.value;
              const k = byName(name);
              // al escribir (o elegir de la lista) el nombre exacto de alguien conocido, se completa lo que aún esté vacío
              set(label, k && !draft[label].role ? { name: k.name, role: k.role, caption_style: k.caption_style, is_source: k.is_source } : { name });
            }} />
          <input placeholder="Cargo" value={draft[label].role} maxLength={120} onChange={(e) => set(label, { role: e.target.value })} />
          <select value={draft[label].caption_style} onChange={(e) => set(label, { caption_style: e.target.value as CaptionStyle })}>
            <option value="sans_upper">Subtítulo: sans MAYÚSCULAS</option>
            <option value="serif_italic">Subtítulo: serif cursiva</option>
          </select>
          <label title="Dónde está en el plano: con el encuadre «Sigue al hablante», el recorte vertical se centra aquí cuando habla">
            Posición en el plano: {Math.round((draft[label].focus_x ?? 0.5) * 100)} % (0 = izquierda, 100 = derecha)
            <input type="range" min={0} max={1} step={0.05} value={draft[label].focus_x ?? 0.5} onChange={(e) => set(label, { focus_x: Number(e.target.value) })} />
          </label>
          <label className="check">
            <input type="checkbox" checked={draft[label].is_source} onChange={(e) => set(label, { is_source: e.target.checked })} />
            Clip citado (B/N)
          </label>
        </div>
      ))}
      {labels.length < 8 && <button className="ghost" onClick={addSpeaker}>+ Añadir speaker</button>}
      <button disabled={!dirty || saving} onClick={async () => { setSaving(true); try { await onSave(draft); } finally { setSaving(false); } }}>
        {saving ? "Guardando…" : "Guardar speakers"}
      </button>
    </div>
  );
}
