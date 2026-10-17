import { memo, useMemo, useState } from "react";
import type { Speaker, Word } from "../types";
import { fmtTime, speakerColor } from "../types";

type Props = {
  words: Word[];
  speakers: Record<string, Speaker>;
  busy: boolean;
  onEditWord: (index: number, text: string) => Promise<void>;
  onAssign: (startIndex: number, endIndex: number, speaker: string) => Promise<void>;
};

type Turn = { speaker: string | undefined; from: number; to: number };

const turnsOf = (words: Word[]): Turn[] => {
  const turns: Turn[] = [];
  words.forEach((w, i) => {
    const last = turns[turns.length - 1];
    if (last && last.speaker === w.speaker) last.to = i;
    else turns.push({ speaker: w.speaker, from: i, to: i });
  });
  return turns;
};

type TurnProps = {
  turn: Turn; words: Word[]; labels: string[]; name: string; sel: [number, number] | null; editing: number | null;
  draft: string; setDraft: (v: string) => void; onClickWord: (i: number, shift: boolean) => void;
  onStartEdit: (i: number) => void; onCommit: () => void; onCancel: () => void;
};

const TurnBlock = memo(function TurnBlock(p: TurnProps) {
  const { turn, words, sel } = p;
  const color = speakerColor(turn.speaker, p.labels);
  return (
    <div className="turn" style={{ borderLeftColor: color }}>
      <div className="turn-head"><span style={{ color }}>{p.name}</span> <span className="ts">{fmtTime(words[turn.from].start)}</span></div>
      <p>
        {words.slice(turn.from, turn.to + 1).map((w, k) => {
          const i = turn.from + k;
          if (p.editing === i) {
            return (
              <input key={i} className="word-edit" autoFocus value={p.draft} size={Math.max(4, p.draft.length)}
                onChange={(e) => p.setDraft(e.target.value)} onBlur={p.onCommit}
                onKeyDown={(e) => { if (e.key === "Enter") p.onCommit(); if (e.key === "Escape") p.onCancel(); }} />
            );
          }
          const selected = sel !== null && i >= sel[0] && i <= sel[1];
          return (
            <span key={i} className={`word${selected ? " sel" : ""}${w.confidence < 0.6 ? " low" : ""}`}
              title={`${fmtTime(w.start)} · confianza ${(w.confidence * 100).toFixed(0)}%`}
              onClick={(e) => p.onClickWord(i, e.shiftKey)} onDoubleClick={() => p.onStartEdit(i)}>
              {w.text}{" "}
            </span>
          );
        })}
      </p>
    </div>
  );
});

export default function TranscriptView({ words, speakers, busy, onEditWord, onAssign }: Props) {
  const labels = useMemo(() => Object.keys(speakers).sort(), [speakers]);
  const turns = useMemo(() => turnsOf(words), [words]);
  const [anchor, setAnchor] = useState<number | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [target, setTarget] = useState("");

  const sel: [number, number] | null = anchor === null || focus === null ? null : [Math.min(anchor, focus), Math.max(anchor, focus)];

  const clickWord = (i: number, shift: boolean) => {
    if (shift && anchor !== null) setFocus(i);
    else { setAnchor(i); setFocus(i); }
  };
  const commit = () => {
    const i = editing;
    setEditing(null);
    const text = draft.trim();
    if (i !== null && text && text !== words[i].text) void onEditWord(i, text);
  };

  return (
    <div className={`transcript${busy ? " busy" : ""}`}>
      {/* Hueco de altura fija: la ayuda y la barra de selección se turnan sin mover el texto. Si la barra
          empujara el contenido al aparecer, el segundo clic de un doble clic caería en otra palabra. */}
      <div className="tv-slot">
        {sel ? (
          <div className="selbar">
            <span>{sel[1] - sel[0] + 1} {sel[1] === sel[0] ? "palabra" : "palabras"} · {fmtTime(words[sel[0]].start)}–{fmtTime(words[sel[1]].end)}</span>
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">Asignar a…</option>
              {labels.map((l) => <option key={l} value={l}>{speakers[l].name || `Speaker ${l}`}</option>)}
            </select>
            <button disabled={!target || busy} onClick={async () => { await onAssign(sel[0], sel[1], target); setAnchor(null); setFocus(null); setTarget(""); }}>Asignar</button>
            <button className="ghost" onClick={() => { setAnchor(null); setFocus(null); }}>Limpiar</button>
          </div>
        ) : (
          <p className="muted hint">Doble clic en una palabra para corregirla · clic y Mayús+clic para elegir un rango y asignarlo a un speaker. Subrayado = poca confianza.</p>
        )}
      </div>
      {turns.map((t) => (
        <TurnBlock key={t.from} turn={t} words={words} labels={labels}
          name={t.speaker ? speakers[t.speaker]?.name || `Speaker ${t.speaker}` : "Sin speaker"}
          sel={sel && sel[1] >= t.from && sel[0] <= t.to ? sel : null}
          editing={editing !== null && editing >= t.from && editing <= t.to ? editing : null}
          draft={draft} setDraft={setDraft} onClickWord={clickWord}
          onStartEdit={(i) => { setEditing(i); setDraft(words[i].text); }}
          onCommit={commit} onCancel={() => setEditing(null)} />
      ))}
    </div>
  );
}
