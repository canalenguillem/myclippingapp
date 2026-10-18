// Cómo ENTRA un gráfico de imagen y el temblor del plano. La entrada deja el contenedor en x = 0, y = 0 en el instante de
// la palabra (`at`), para que el efecto final (vaporizar, partir, explotar) actúe sobre un elemento ya asentado.
//   pop          rebote en el sitio (por defecto)
//   punch        llega desde la izquierda acelerando (u²), golpea EN la palabra y rebota; tiembla el plano
//   slide_left / slide_right / slide_top   se desliza desde fuera del cuadro en 0,45 s
//   drop         cae desde arriba y rebota al llegar a la palabra
import { mulberry32 } from "../rng.mjs";

export const ENTRIES = ["pop", "punch", "slide_left", "slide_right", "slide_top", "drop"];
export const MOVING = new Set(["punch", "slide_left", "slide_right", "slide_top", "drop"]);

const fmt = (n) => Number(n.toFixed(3));

/** Temblor del plano: sacude el vídeo (`#vwrap`) con una amplitud que decae; a 1,03 de escala para no enseñar bordes. */
export function shakeScript({ at, amp = 16, seed = 1 }) {
  const rand = mulberry32(seed * 6151 + 3);
  const parts = [`tl.to("#vwrap",{scale:1.03,duration:0.04,ease:"none"},${fmt(Math.max(0, at - 0.02))});`];
  const steps = 8;
  for (let i = 0; i < steps; i++) {
    const k = 1 - i / steps;
    const x = (rand() - 0.5) * 2 * amp * k;
    const y = (rand() - 0.5) * 2 * amp * k;
    parts.push(`tl.to("#vwrap",{x:${fmt(x)},y:${fmt(y)},duration:0.04,ease:"none"},${fmt(at + i * 0.04)});`);
  }
  parts.push(`tl.to("#vwrap",{x:0,y:0,scale:1,duration:0.06,ease:"power2.out"},${fmt(at + steps * 0.04)});`);
  return parts.join("");
}

/** @param {{id:string, entry:string, t0:number, at:number, box:{w:number,h:number}, left:number, top:number, tilt:number}} p */
export function entryScript({ id, entry, t0, at, box, left, top, tilt }) {
  const sel = `#${id}`;
  const offLeft = -(left + box.w + 80);
  const offRight = 1080 - left + 80;
  const offTop = -(top + box.h + 80);
  const sfx = [];
  const parts = [];
  switch (entry) {
    case "punch": {
      parts.push(
        `tl.fromTo("${sel}",{opacity:1,x:${fmt(offLeft)},scale:0.7,rotation:${tilt}},{x:0,scale:1,rotation:${tilt},duration:${fmt(Math.max(0.25, at - t0))},ease:"power3.in"},${fmt(t0)});`,
        `tl.to("${sel}",{x:-45,scale:1.12,duration:0.09,ease:"power2.out"},${fmt(at)});`,
        `tl.to("${sel}",{x:0,scale:1,duration:0.3,ease:"power2.inOut"},${fmt(at + 0.09)});`,
        shakeScript({ at, seed: Number(id.replace(/\D/g, "")) || 1 }),
      );
      sfx.push({ kind: "whoosh", at: t0 }, { kind: "thud", at });
      break;
    }
    case "slide_left":
    case "slide_right":
    case "slide_top": {
      const from = entry === "slide_top" ? `y:${fmt(offTop)}` : `x:${fmt(entry === "slide_left" ? offLeft : offRight)}`;
      const to = entry === "slide_top" ? "y:0" : "x:0";
      parts.push(`tl.fromTo("${sel}",{opacity:1,${from},rotation:${tilt}},{${to},rotation:${tilt},duration:0.45,ease:"power3.out"},${fmt(t0)});`);
      sfx.push({ kind: "whoosh", at: t0 });
      break;
    }
    case "drop": {
      parts.push(
        `tl.fromTo("${sel}",{opacity:1,y:${fmt(offTop)},rotation:${tilt}},{y:0,rotation:${tilt},duration:${fmt(Math.max(0.25, at - t0))},ease:"power2.in"},${fmt(t0)});`,
        `tl.fromTo("${sel}",{y:0},{y:-40,duration:0.12,ease:"power2.out",yoyo:true,repeat:1},${fmt(at)});`,
      );
      sfx.push({ kind: "thud", at });
      break;
    }
    default: {
      parts.push(
        `tl.fromTo("${sel}",{opacity:0,scale:0.55,y:40,rotation:${tilt}},{opacity:1,scale:1,y:0,rotation:${tilt},duration:0.42,ease:"back.out(1.7)"},${fmt(t0)});`,
      );
      sfx.push({ kind: "pop", at: t0 });
    }
  }
  return { script: parts.join(""), sfx };
}
