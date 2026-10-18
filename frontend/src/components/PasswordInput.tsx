import { useState } from "react";

type Props = { value: string; onChange: (v: string) => void; autoComplete: string };

/** Campo de contraseña con botón para ver lo escrito. */
export default function PasswordInput({ value, onChange, autoComplete }: Props) {
  const [shown, setShown] = useState(false);
  return (
    <span className="pw">
      <input type={shown ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)}
        required minLength={8} autoComplete={autoComplete} />
      <button type="button" className="ghost" onClick={() => setShown((s) => !s)} aria-pressed={shown}>{shown ? "Ocultar" : "Ver"}</button>
    </span>
  );
}
