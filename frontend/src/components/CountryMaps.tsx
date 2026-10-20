import { useState } from "react";
import { api } from "../api";
import type { Asset } from "../types";

type Props = { assets: Asset[]; onAdded: (made: Asset[]) => void; onError: (message: string) => void };

/** Genera el mapa de uno o varios países (y de Europa) y los añade a la librería de imágenes. */
export default function CountryMaps({ assets, onAdded, onError }: Props) {
  const [open, setOpen] = useState(false);
  const [countries, setCountries] = useState<{ name: string; group: string }[]>([]);
  const [pick, setPick] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const fail = (e: unknown) => onError(e instanceof Error ? e.message : String(e));

  const toggle = () => {
    setOpen((o) => !o);
    if (countries.length === 0) api<{ name: string; group: string }[]>("/api/assets/maps/countries").then(setCountries).catch(fail);
  };
  const add = async () => {
    onError(""); setAdding(true);
    try {
      onAdded(await api<Asset[]>("/api/assets/maps", { json: { countries: pick } }));
      setPick([]);
    } catch (e) { fail(e); } finally { setAdding(false); }
  };

  return (
    <>
      <div className="gfx-lib">
        <button className="ghost" onClick={toggle}>{open ? "▾" : "▸"} Mapas de países</button>
        <span className="muted hint">Genera el mapa de un país (rojo, con los vecinos tenues) y úsalo como una imagen más o como objeto que orbita en la cortinilla.</span>
      </div>
      {open && (
        <div className="gfx-maps">
          {["Europa", "Otros"].map((group) => (
            <div key={group}>
              <div className="gfx-maps-head">
                <strong>{group}</strong>
                <button className="ghost" onClick={() => { const names = countries.filter((c) => c.group === group && c.name !== "Europa").map((c) => c.name); setPick((p) => [...new Set([...p, ...names])]); }}>Marcar todos</button>
              </div>
              <div className="gfx-maps-chips">
                {countries.filter((c) => c.group === group).map((c) => {
                  const have = assets.some((a) => a.kind === "map" && a.name === `Mapa de ${c.name}`);
                  return (
                    <label key={c.name} className={`check gfx-chip${have ? " have" : ""}`}>
                      <input type="checkbox" disabled={have} checked={have || pick.includes(c.name)}
                        onChange={(e) => setPick((p) => e.target.checked ? [...p, c.name] : p.filter((n) => n !== c.name))} />
                      {c.name}
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
          <button disabled={pick.length === 0 || adding} onClick={add}>{adding ? "Generando…" : `Añadir ${pick.length} mapa${pick.length === 1 ? "" : "s"}`}</button>
        </div>
      )}
    </>
  );
}
