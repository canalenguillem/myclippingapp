// Mapa de tiempos único del render (mismo criterio que backend/app/services/cortinilla.py):
//   t_salida = t_origen + duración de la cortinilla, si t_origen >= at.
// Todo lo que se coloca por tiempo (subtítulos, gancho, blanco y negro…) pasa por aquí.

const round = (n) => Number(n.toFixed(3));

/** @param {{at:number, duration:number}|undefined} cortinilla */
export function makeTimeMap(cortinilla) {
  const at = cortinilla?.at ?? null;
  const seconds = cortinilla?.duration ?? 0;
  return {
    at,
    seconds,
    out: (t) => round(at !== null && t >= at ? t + seconds : t),
    total: (clipDuration) => round(clipDuration + seconds),
  };
}

/** Parte los tramos [a, b] que cruzan la inserción en dos (antes y después), ya en tiempo de salida. */
export function mapIntervals(intervals, map) {
  const out = [];
  for (const [a, b] of intervals) {
    if (map.at !== null && a < map.at && b > map.at) {
      out.push([map.out(a), map.at], [map.out(map.at), map.out(b)]);
    } else out.push([map.out(a), map.out(b)]);
  }
  return out;
}
