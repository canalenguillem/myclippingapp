// Motivo `puppets`: monigotes de comic de palo con la cara de cada uno como cabeza, cogidos de la mano (§8 del md, «muñecos»).
// Entran andando desde la izquierda (las piernas se balancean) y, EN la palabra, dan un saltito y alzan las manos unidas.
// Siempre se ve que es un dibujo: cuerpo de palo, trazo grueso y cabeza en círculo; nunca una imagen que pueda pasar por real.
import { escapeHtml } from "../html.mjs";

const fmt = (n) => Number(n.toFixed(3));
const S = 190;            // separación entre monigotes
const H = 260;            // alto del dibujo
const HEAD = { cy: 62, r: 56 };
const SHOULDER = 130, HIP = 190, FOOT = 252, HAND = 182;
const MAX_SCALE = 1.3;
const INK = "#1D1A17", EDGE = "#F3EEE2";

const line = (x1, y1, x2, y2, extra = "") => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" ${extra}/>`;

export function puppetsMotif({ id, item, t0, at, t1, zones, files }) {
  const n = item.images.length;
  const W = S * n;
  const scale = Math.min(MAX_SCALE, Math.max(0.5, (1632 - zones.card) / H), 1000 / W);
  const w = Math.round(W * scale), h = Math.round(H * scale);
  const left = Math.round((1080 - w) / 2);
  const figures = item.images.map((image, i) => {
    const cx = S * i + S / 2;
    const src = files[image];
    const leftHand = i === 0 ? [cx - 44, 205] : [cx - S / 2, HAND];   // el primero deja caer el brazo libre; los demás cogen al anterior
    const rightHand = i === n - 1 ? [cx + 44, 205] : [cx + S / 2, HAND];
    const body = [
      line(cx, HEAD.cy + HEAD.r, cx, HIP),                                  // cuello y torso
      line(cx, SHOULDER, ...leftHand), line(cx, SHOULDER, ...rightHand),      // brazos
    ].join("");
    const legs = `<g id="${id}a${i}">${line(cx, HIP, cx - 34, FOOT)}</g><g id="${id}b${i}">${line(cx, HIP, cx + 34, FOOT)}</g>`;
    const head = `<clipPath id="${id}c${i}"><circle cx="${cx}" cy="${HEAD.cy}" r="${HEAD.r}"/></clipPath>` +
      `<image href="${escapeHtml(src)}" x="${cx - HEAD.r}" y="${HEAD.cy - HEAD.r}" width="${HEAD.r * 2}" height="${HEAD.r * 2}" preserveAspectRatio="xMidYMid slice" clip-path="url(#${id}c${i})"/>` +
      `<circle cx="${cx}" cy="${HEAD.cy}" r="${HEAD.r}" fill="none" class="pk"/>`;
    return `<g id="${id}f${i}">${body}${legs}<g id="${id}h${i}">${head}</g></g>`;
  });
  // contorno crema (dos sombras sin desenfoque) para que el trazo negro se lea sobre cualquier fondo
  const html = `<div id="${id}" class="gfx pp"><svg viewBox="0 0 ${W} ${H}" width="${w}" height="${h}" overflow="visible">${figures.join("")}</svg></div>`;
  const css = `.pp svg{display:block;filter:drop-shadow(0 0 2px ${EDGE}) drop-shadow(0 0 2px ${EDGE}) drop-shadow(0 8px 10px rgba(0,0,0,.45))}
.pp line{stroke:${INK};stroke-width:12;stroke-linecap:round}
.pp .pk{stroke:${INK};stroke-width:8}`;
  const walkEnd = Math.max(t0 + 0.6, at - 0.05);
  const hops = Math.max(2, Math.round((walkEnd - t0) / 0.18));
  const exit = fmt(Math.max(at + 0.5, t1 - 0.3));
  const parts = [
    `tl.fromTo("#${id}",{opacity:1,x:${-(left + w + 30)}},{x:0,duration:${fmt(walkEnd - t0)},ease:"power2.out"},${fmt(t0)});`,
    `tl.fromTo("#${id}",{y:0},{y:-10,duration:0.09,yoyo:true,repeat:${hops},ease:"sine.inOut"},${fmt(t0)});`,
  ];
  for (let i = 0; i < n; i++) {
    const cx = S * i + S / 2;
    parts.push(
      `tl.fromTo("#${id}a${i}",{rotation:-22,svgOrigin:"${cx} ${HIP}"},{rotation:22,duration:0.18,yoyo:true,repeat:${hops},ease:"sine.inOut"},${fmt(t0)});`,
      `tl.fromTo("#${id}b${i}",{rotation:22,svgOrigin:"${cx} ${HIP}"},{rotation:-22,duration:0.18,yoyo:true,repeat:${hops},ease:"sine.inOut"},${fmt(t0)});`,
      `tl.fromTo("#${id}h${i}",{scale:1,svgOrigin:"${cx} ${HEAD.cy + HEAD.r}"},{scale:1.18,duration:0.12,yoyo:true,repeat:1,ease:"power2.out"},${fmt(at)});`,
    );
  }
  parts.push(
    `tl.fromTo("#${id}",{y:0},{y:-26,duration:0.14,yoyo:true,repeat:1,ease:"power2.out"},${fmt(at)});`,   // saltito de alegría en la palabra
    `tl.to("#${id}",{opacity:0,duration:0.3,ease:"power3.in"},${exit});`,
    `tl.set("#${id}",{visibility:"hidden"},${fmt(t1)});`,
  );
  return { sfx: [{ kind: "whoosh", at: t0 }, { kind: "pop", at }], html, css, cssItem: `#${id}{left:${left}px;top:${zones.card}px;width:${w}px;height:${h}px}`, script: parts.join("") };
}
