import { useEffect, useState } from "react";
import type { CaptionStyle, Speaker } from "../types";
import { speakerColor } from "../types";

type Props = { speakers: Record<string, Speaker>; onSave: (s: Record<string, Speaker>) => Promise<void> };

export default function SpeakerPanel({ speakers, onSave }: Props) {
  const [draft, setDraft] = useState(speakers);
  const [saving, setSaving] = useState(false);
  // El padre consulta el proyecto cada pocos segundos y cada respuesta es un objeto nuevo: reiniciar el borrador
  // por identidad borraba lo que el usuario estaba escribiendo. Solo se reinicia si el CONTENIDO cambia.
  const serverState = JSON.stringify(speakers);
  useEffect(() => setDraft(JSON.parse(serverState)), [serverState]);

  const labels = Object.keys(draft).sort();
  const dirty = JSON.stringify(draft) !== JSON.stringify(speakers);
  const set = (label: string, patch: Partial<Speaker>) => setDraft((d) => ({ ...d, [label]: { ...d[label], ...patch } }));

  const addSpeaker = () => {
    const next = "ABCDEFGH".split("").find((l) => !(l in draft));
    if (next) setDraft((d) => ({ ...d, [next]: { name: "", role: "", caption_style: "sans_upper", is_source: false } }));
  };

  if (labels.length === 0) return <p className="muted">Sin speakers todavía.</p>;
  return (
    <div className="speakers">
      {labels.map((label) => (
        <div className="speaker-card" key={label} style={{ borderLeftColor: speakerColor(label, labels) }}>
          <strong>Speaker {label}</strong>
          <input placeholder="Nombre" value={draft[label].name} maxLength={80} onChange={(e) => set(label, { name: e.target.value })} />
          <input placeholder="Cargo" value={draft[label].role} maxLength={120} onChange={(e) => set(label, { role: e.target.value })} />
          <select value={draft[label].caption_style} onChange={(e) => set(label, { caption_style: e.target.value as CaptionStyle })}>
            <option value="sans_upper">Subtítulo: sans MAYÚSCULAS</option>
            <option value="serif_italic">Subtítulo: serif cursiva</option>
          </select>
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
