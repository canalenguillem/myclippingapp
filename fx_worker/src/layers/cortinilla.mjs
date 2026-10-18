// Cortinilla de inicio «pill_draw» (§6 del md). Se INSERTA entre dos instantes del clip (el clip se pausa); en tiempo
// de salida ocupa [at, at + duration]. Línea de tiempo (s relativos a la cortinilla, para 3,6 s):
//   0–0,42     barrido curvo con canto blanco que tapa el último fotograma
//   0,30/0,48  título: palabras en sans y la última en serif cursiva, entran desenfocadas
//   0,55–1,50  una línea blanca dibuja la píldora (desde arriba-centro, en sentido horario)
//   0,95       tarjeta con el objeto que orbita por la píldora (0,30 vueltas/s)
//   1,55       antetítulo en mono con tracking
//   2,75–3,35  la cola de la línea persigue a la cabeza; textos y tarjeta salen desenfocados
//   3,18–3,60  barrido de salida: el color se va y descubre el siguiente fotograma
// Con otra duración, lo de la entrada se comprime si dura menos de 3,6 s y lo de la salida se ancla al final.
import { escapeHtml } from "../html.mjs";

export const SWEEP = 0.42;
const BASE = 3.6;
const PW = 900;
const PH = 300;
const R = PH / 2;
const STRAIGHT = PW - PH;
const ARC = Math.PI * R;
export const PERIMETER = 2 * STRAIGHT + 2 * ARC;
const ORBIT_SPEED = 0.3; // vueltas por segundo
const CARD = 150;
const CX = 540;
const CY = 960;

const fmt = (n) => Number(n.toFixed(3));

/** Punto de la píldora a `s` px del arranque (arriba-centro, sentido horario), por longitud de arco. */
export function pillPoint(s) {
  s = ((s % PERIMETER) + PERIMETER) % PERIMETER;
  const half = STRAIGHT / 2;
  if (s < half) return [CX + s, CY - R]; // recto superior, hacia la derecha
  s -= half;
  if (s < ARC) {
    const a = -Math.PI / 2 + (s / ARC) * Math.PI;
    return [CX + half + R * Math.cos(a), CY + R * Math.sin(a)];
  }
  s -= ARC;
  if (s < STRAIGHT) return [CX + half - s, CY + R]; // recto inferior, hacia la izquierda
  s -= STRAIGHT;
  if (s < ARC) {
    const a = Math.PI / 2 + (s / ARC) * Math.PI;
    return [CX - half + R * Math.cos(a), CY + R * Math.sin(a)];
  }
  s -= ARC;
  return [CX - half + s, CY - R]; // recto superior, de vuelta al arranque
}

/** El título sale en dos partes: todas las palabras menos la última en sans y la última en serif cursiva. */
export function splitTitle(title) {
  const words = title.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return { lead: "", accent: "" };
  return { lead: words.slice(0, -1).join(" "), accent: words[words.length - 1] };
}

/** Tamaños que caben dentro de la píldora (780 px de ancho útil), sin pasar de 116/138 px ni bajar de 48. */
export function titleSizes({ lead, accent }) {
  const width = (sans, serif) => lead.length * 0.62 * sans + (lead && accent ? 0.3 * sans : 0) + accent.length * 0.5 * serif;
  let k = 1;
  const need = width(116, 138);
  if (need > 780) k = Math.max(48 / 116, 780 / need);
  return { sans: Math.round(116 * k), serif: Math.round(138 * k) };
}

export function cortinillaLayer({ at, duration, color, title = "", kicker = "", orbit = null, fps = 30 }) {
  const k = Math.min(1, duration / BASE); // la entrada se comprime en cortinillas cortas
  const enter = (x) => fmt(at + x * k);
  const exit = (x) => fmt(at + duration - (BASE - x) * k); // anclado al final: 2,75 → duration − 0,85
  const t = splitTitle(title);
  const sizes = titleSizes(t);
  const hasTitle = Boolean(t.lead || t.accent);

  const half = STRAIGHT / 2;
  const pillPath = `M ${CX} ${CY - R} H ${CX + half} A ${R} ${R} 0 0 1 ${CX + half} ${CY + R} H ${CX - half} A ${R} ${R} 0 0 1 ${CX - half} ${CY - R} Z`;
  const perim = fmt(PERIMETER);

  const sweepSvg = `<svg id="sweep" class="sweep" width="1560" height="1920" viewBox="0 0 1560 1920">
      <path d="M0 0 H1230 Q1560 960 1230 1920 H0 Z" fill="#fff" transform="translate(46 0)"/>
      <path d="M0 0 H1230 Q1560 960 1230 1920 H0 Z" fill="${color}"/>
    </svg>`;
  const html = `<div id="cort" class="clip" data-start="${fmt(at)}" data-duration="${fmt(duration)}" data-track-index="5">
    ${sweepSvg}
    ${hasTitle ? `<div id="ctitle">${t.lead ? `<span id="t1">${escapeHtml(t.lead)}</span>` : ""}${t.accent ? `<span id="t2">${escapeHtml(t.accent)}</span>` : ""}</div>` : ""}
    <svg id="pillsvg" width="1080" height="1920" viewBox="0 0 1080 1920">
      <path id="pill" d="${pillPath}" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-dasharray="${perim}" stroke-dashoffset="${perim}"/>
      <line id="pillmark" x1="${CX}" y1="${CY - R - 14}" x2="${CX}" y2="${CY - R + 14}" stroke="#fff" stroke-width="4" stroke-linecap="round" opacity="0"/>
    </svg>
    <div id="corbit">${orbit ? `<img src="${orbit}" alt=""/>` : "<i></i>"}</div>
    ${kicker ? `<div id="ckicker">${escapeHtml(kicker.toUpperCase())}</div>` : ""}
  </div>`;
  const css = `#cort{position:absolute;inset:0}
.sweep{position:absolute;left:0;top:0;will-change:transform}
#ctitle{position:absolute;left:0;top:${CY - 110}px;width:1080px;height:220px;display:flex;align-items:center;justify-content:center;gap:0.3em;font-size:${sizes.sans}px;color:#fff;white-space:nowrap}
#t1{display:inline-block;font-family:InterX,sans-serif;font-weight:800;font-size:${sizes.sans}px;opacity:0}
#t2{display:inline-block;font-family:CormorantX,serif;font-style:italic;font-weight:600;font-size:${sizes.serif}px;opacity:0}
#pillsvg{position:absolute;left:0;top:0}
#corbit{position:absolute;left:0;top:0;width:${CARD}px;height:${CARD}px;border-radius:22px;background:#fff;box-shadow:0 10px 14px rgba(0,0,0,.35);opacity:0;display:flex;align-items:center;justify-content:center;overflow:hidden}
#corbit img{width:100%;height:100%;object-fit:contain;padding:14px}
#corbit i{width:90px;height:90px;border-radius:12px;background:${color}}
#ckicker{position:absolute;left:0;top:${CY + R + 60}px;width:1080px;text-align:center;font-family:JetBrainsX,monospace;font-weight:500;font-size:26px;letter-spacing:9px;color:#fff;opacity:0}`;

  const orbitStart = at + 0.95 * k;
  const orbitEnd = at + duration - (BASE - 2.75) * k;
  const sets = [];
  for (let time = orbitStart; time < orbitEnd; time += 1 / fps) {
    const [x, y] = pillPoint((time - orbitStart) * ORBIT_SPEED * PERIMETER);
    sets.push(`tl.set("#corbit",{x:${(x - CARD / 2).toFixed(1)},y:${(y - CARD / 2).toFixed(1)}},${fmt(time)});`);
  }
  const blurIn = (sel, x) => `tl.fromTo("${sel}",{opacity:0,y:24,filter:"blur(14px)"},{opacity:1,y:0,filter:"blur(0px)",duration:${fmt(0.45 * k)},ease:"power3.out"},${enter(x)});`;
  const script = [
    `tl.fromTo("#sweep",{x:-1560},{x:0,duration:${SWEEP},ease:"power2.inOut"},${fmt(at)});`,
    t.lead ? blurIn("#t1", 0.3) : "",
    t.accent ? blurIn("#t2", 0.48) : "",
    `tl.set("#pillmark",{opacity:1},${enter(0.55)});`,
    `tl.fromTo("#pill",{strokeDashoffset:${perim}},{strokeDashoffset:0,duration:${fmt(0.95 * k)},ease:"power1.inOut"},${enter(0.55)});`,
    `tl.fromTo("#corbit",{opacity:0,scale:0},{opacity:1,scale:1,duration:${fmt(0.35 * k)},ease:"back.out(2.2)"},${enter(0.95)});`,
    ...sets,
    kicker ? blurIn("#ckicker", 1.55) : "",
    `tl.to("#pill",{strokeDashoffset:${-perim},duration:${fmt(0.45 * k)},ease:"power1.in"},${exit(2.7)});`,
    `tl.set("#pillmark",{opacity:0},${exit(2.7)});`,
    `tl.to(${JSON.stringify(["#t1", "#t2", "#corbit", "#ckicker"].filter((s) => (s === "#t1" ? t.lead : s === "#t2" ? t.accent : s === "#ckicker" ? kicker : true)))},{opacity:0,filter:"blur(10px)",duration:${fmt(0.45 * k)},ease:"power3.in"},${exit(2.75)});`,
    `tl.to("#sweep",{x:1560,duration:${SWEEP},ease:"power2.inOut"},${fmt(at + duration - SWEEP)});`,
  ].filter(Boolean).join("\n");
  return { html, css, script };
}
