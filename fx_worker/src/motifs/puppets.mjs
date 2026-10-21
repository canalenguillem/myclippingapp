// Motivo `puppets`: monigotes de comic con la cara de cada uno como cabeza, cogidos de la mano (§8 del md, «muñecos»).
//   look "southpark" (por defecto): recortables de cabeza enorme, traje o abrigo planos y brazos y piernas cortos; caminan balanceándose.
//   look "stick": monigotes de palo con trazo grueso.
// Entran andando desde la izquierda y, EN la palabra, dan un saltito. Siempre se ve que es un dibujo (cuerpo plano de comic y la
// cara en un círculo); nunca una imagen que pueda pasar por real.
import { escapeHtml } from "../html.mjs";

const fmt = (n) => Number(n.toFixed(3));
const S = 190;            // separación entre monigotes
const H = 260;            // alto del dibujo
const HEAD = { cy: 62, r: 56 };
const SHOULDER = 130, HIP = 190, FOOT = 252, HAND = 182;
const MAX_SCALE = 1.3;
const INK = "#1D1A17", EDGE = "#F3EEE2";

const line = (x1, y1, x2, y2, extra = "") => `<line class="st" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" ${extra}/>`;

function stickFigure({ id, i, n, cx, src }) {
  const leftHand = i === 0 ? [cx - 44, 205] : [cx - S / 2, HAND];   // el primero deja caer el brazo libre; los demás cogen al anterior
  const rightHand = i === n - 1 ? [cx + 44, 205] : [cx + S / 2, HAND];
  const body = [line(cx, HEAD.cy + HEAD.r, cx, HIP), line(cx, SHOULDER, ...leftHand), line(cx, SHOULDER, ...rightHand)].join("");
  const legs = `<g id="${id}a${i}">${line(cx, HIP, cx - 34, FOOT)}</g><g id="${id}b${i}">${line(cx, HIP, cx + 34, FOOT)}</g>`;
  const head = `<clipPath id="${id}c${i}"><circle cx="${cx}" cy="${HEAD.cy}" r="${HEAD.r}"/></clipPath>` +
    `<image href="${src}" x="${cx - HEAD.r}" y="${HEAD.cy - HEAD.r}" width="${HEAD.r * 2}" height="${HEAD.r * 2}" preserveAspectRatio="xMidYMid slice" clip-path="url(#${id}c${i})"/>` +
    `<circle cx="${cx}" cy="${HEAD.cy}" r="${HEAD.r}" fill="none" class="pk"/>`;
  return `<g id="${id}f${i}">${body}${legs}<g id="${id}h${i}">${head}</g></g>`;
}


// --- estilo South Park: cuerpos de recortable -------------------------------------------------------------------
const SP = { H: 275, head: { cy: 78, r: 70 }, shoulderY: 160, hipY: 228, footY: 262 };
const SKIN = "#F2C9A0";
const OUTFITS = [
  { top: "#37393F", legs: "#2B2D32", shoes: "#111", trim: "suit" },     // traje oscuro con camisa blanca y corbata roja
  { top: "#8A5A33", legs: "#4A6FA5", shoes: "#5B3A1E", trim: "coat" },  // abrigo marrón con cuello azul y botones
  { top: "#E87B1E", legs: "#2B3A67", shoes: "#222", trim: "parka" },    // parka naranja
];
const ol = 'stroke="#1D1A17" stroke-width="3" stroke-linejoin="round"';

function southParkFigure({ id, i, n, cx, src, accent = "#DA2E09" }) {
  const o = OUTFITS[i % OUTFITS.length];
  const { head, shoulderY, hipY, footY } = SP;
  const armTo = (side) => {                                   // `side` -1 izquierda, +1 derecha
    const joined = side === -1 ? i > 0 : i < n - 1;           // con vecino: la mano llega al punto medio; si no, cuelga
    return joined ? [cx + side * (S / 2), shoulderY + 30] : [cx + side * 66, shoulderY + 52];
  };
  const arm = (side) => {
    const [hx, hy] = armTo(side);
    return `<line x1="${cx + side * 36}" y1="${shoulderY + 8}" x2="${hx}" y2="${hy}" stroke="#1D1A17" stroke-width="30" stroke-linecap="round"/>` +
      `<line x1="${cx + side * 36}" y1="${shoulderY + 8}" x2="${hx}" y2="${hy}" stroke="${o.top}" stroke-width="24" stroke-linecap="round"/>` +
      (side === 1 && i < n - 1 ? "" : `<circle cx="${hx}" cy="${hy}" r="13" fill="${SKIN}" ${ol}/>`);
  };
  const clasp = i < n - 1 ? `<circle cx="${cx + S / 2}" cy="${shoulderY + 30}" r="15" fill="${SKIN}" ${ol}/>` : "";
  const trim =
    o.trim === "suit"
      ? `<polygon points="${cx - 16},${shoulderY} ${cx + 16},${shoulderY} ${cx},${shoulderY + 30}" fill="#F3EEE2" ${ol}/>` +
        `<polygon points="${cx - 7},${shoulderY + 12} ${cx + 7},${shoulderY + 12} ${cx + 5},${shoulderY + 58} ${cx},${shoulderY + 68} ${cx - 5},${shoulderY + 58}" fill="${accent}" ${ol}/>`
      : o.trim === "coat"
        ? `<polygon points="${cx - 22},${shoulderY} ${cx + 22},${shoulderY} ${cx},${shoulderY + 24}" fill="#7FA6D6" ${ol}/>` +
          `<circle cx="${cx}" cy="${shoulderY + 38}" r="4" fill="#1D1A17"/><circle cx="${cx}" cy="${shoulderY + 56}" r="4" fill="#1D1A17"/>`
        : `<line x1="${cx}" y1="${shoulderY}" x2="${cx}" y2="${hipY}" stroke="#1D1A17" stroke-width="3"/>`;
  const body =
    `<rect x="${cx - 32}" y="${hipY - 6}" width="26" height="${footY - hipY + 2}" rx="4" fill="${o.legs}" ${ol}/>` +
    `<rect x="${cx + 6}" y="${hipY - 6}" width="26" height="${footY - hipY + 2}" rx="4" fill="${o.legs}" ${ol}/>` +
    `<ellipse cx="${cx - 22}" cy="${footY + 4}" rx="19" ry="8" fill="${o.shoes}" ${ol}/><ellipse cx="${cx + 22}" cy="${footY + 4}" rx="19" ry="8" fill="${o.shoes}" ${ol}/>` +
    arm(-1) + arm(1) +
    `<rect x="${cx - 44}" y="${shoulderY - 6}" width="88" height="${hipY - shoulderY + 10}" rx="14" fill="${o.top}" ${ol}/>` + trim;
  const face =
    `<clipPath id="${id}c${i}"><circle cx="${cx}" cy="${head.cy}" r="${head.r}"/></clipPath>` +
    `<circle cx="${cx}" cy="${head.cy}" r="${head.r}" fill="${SKIN}"/>` +
    `<image href="${src}" x="${cx - head.r}" y="${head.cy - head.r}" width="${head.r * 2}" height="${head.r * 2}" preserveAspectRatio="xMidYMid slice" clip-path="url(#${id}c${i})"/>` +
    `<circle cx="${cx}" cy="${head.cy}" r="${head.r}" fill="none" stroke="#1D1A17" stroke-width="5"/>`;
  return { html: `<g id="${id}f${i}">${body}<g id="${id}h${i}">${face}</g></g>`, clasp };
}

export function puppetsMotif({ id, item, t0, at, t1, zones, files, accent = "#DA2E09" }) {
  const n = item.images.length;
  const look = item.look ?? "southpark";
  const W = S * n;
  const Hh = look === "stick" ? H : SP.H;
  const scale = Math.min(MAX_SCALE, Math.max(0.5, (1632 - zones.card) / Hh), 1000 / W);
  const w = Math.round(W * scale), h = Math.round(Hh * scale);
  const left = Math.round((1080 - w) / 2);
  const figures = [];
  let clasps = "";
  item.images.forEach((image, i) => {
    const cx = S * i + S / 2;
    const src = escapeHtml(files[image]);
    if (look === "stick") figures.push(stickFigure({ id, i, n, cx, src }));
    else {
      const f = southParkFigure({ id, i, n, cx, src, accent });
      figures.push(f.html);
      clasps += f.clasp;
    }
  });
  const html = `<div id="${id}" class="gfx pp"><svg viewBox="0 0 ${W} ${Hh}" width="${w}" height="${h}" overflow="visible">${figures.join("")}${clasps}</svg></div>`;
  const css = `.pp svg{display:block;filter:drop-shadow(0 0 2px ${EDGE}) drop-shadow(0 0 2px ${EDGE}) drop-shadow(0 8px 10px rgba(0,0,0,.45))}
.pp line.st{stroke:${INK};stroke-width:12;stroke-linecap:round}
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
    if (look === "stick") {
      parts.push(
        `tl.fromTo("#${id}a${i}",{rotation:-22,svgOrigin:"${cx} ${HIP}"},{rotation:22,duration:0.18,yoyo:true,repeat:${hops},ease:"sine.inOut"},${fmt(t0)});`,
        `tl.fromTo("#${id}b${i}",{rotation:22,svgOrigin:"${cx} ${HIP}"},{rotation:-22,duration:0.18,yoyo:true,repeat:${hops},ease:"sine.inOut"},${fmt(t0)});`,
      );
    } else {
      // andar de recortable: el cuerpo se balancea de lado a lado sobre los pies
      parts.push(`tl.fromTo("#${id}f${i}",{rotation:${i % 2 ? 5 : -5},svgOrigin:"${cx} ${SP.footY}"},{rotation:${i % 2 ? -5 : 5},duration:0.18,yoyo:true,repeat:${hops},ease:"sine.inOut"},${fmt(t0)});`);
    }
    const headBase = look === "stick" ? HEAD.cy + HEAD.r : SP.head.cy + SP.head.r;
    parts.push(`tl.fromTo("#${id}h${i}",{scale:1,svgOrigin:"${cx} ${headBase}"},{scale:1.15,duration:0.12,yoyo:true,repeat:1,ease:"power2.out"},${fmt(at)});`);
  }
  parts.push(
    `tl.fromTo("#${id}",{y:0},{y:-26,duration:0.14,yoyo:true,repeat:1,ease:"power2.out"},${fmt(at)});`,   // saltito de alegría en la palabra
    `tl.to("#${id}",{opacity:0,duration:0.3,ease:"power3.in"},${exit});`,
    `tl.set("#${id}",{visibility:"hidden"},${fmt(t1)});`,
  );
  return { sfx: [{ kind: "whoosh", at: t0 }, { kind: "pop", at }], html, css, cssItem: `#${id}{left:${left}px;top:${zones.card}px;width:${w}px;height:${h}px}`, script: parts.join("") };
}
