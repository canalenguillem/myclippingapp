// Efectos de sonido sintetizados (§10 del md): sin bancos de sonido de terceros y deterministas (misma semilla, mismos
// bytes). Mono, 16 bits, 48 kHz. Los niveles son bajos a propósito: los efectos van SIEMPRE por debajo de la voz.
import { mulberry32 } from "./rng.mjs";

export const SAMPLE_RATE = 48000;
const PEAK = 0.5; // pico del fichero; el volumen final lo fija `data-volume` en la composición

/** Cabecera RIFF/WAVE de PCM de 16 bits, mono. */
function wav(samples) {
  const data = Buffer.alloc(samples.length * 2);
  for (let i = 0; i < samples.length; i++) data.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(samples[i] * 32767))), i * 2);
  const head = Buffer.alloc(44);
  head.write("RIFF", 0);
  head.writeUInt32LE(36 + data.length, 4);
  head.write("WAVEfmt ", 8);
  head.writeUInt32LE(16, 16);
  head.writeUInt16LE(1, 20); // PCM
  head.writeUInt16LE(1, 22); // mono
  head.writeUInt32LE(SAMPLE_RATE, 24);
  head.writeUInt32LE(SAMPLE_RATE * 2, 28);
  head.writeUInt16LE(2, 32);
  head.writeUInt16LE(16, 34);
  head.write("data", 36);
  head.writeUInt32LE(data.length, 40);
  return Buffer.concat([head, data]);
}

/** Filtro de paso banda de variable de estado (Chamberlin) con frecuencia central variable en el tiempo. */
function bandpassNoise(count, seed, centerAt, q) {
  const rand = mulberry32(seed);
  const out = new Float64Array(count);
  let low = 0;
  let band = 0;
  for (let i = 0; i < count; i++) {
    const noise = rand() * 2 - 1;
    const f = 2 * Math.sin((Math.PI * Math.min(centerAt(i / count), SAMPLE_RATE / 6)) / SAMPLE_RATE);
    low += f * band;
    const high = noise - low - band / q;
    band += f * high;
    out[i] = band;
  }
  return out;
}

function shape(samples, envelope) {
  let peak = 1e-9;
  for (let i = 0; i < samples.length; i++) {
    samples[i] *= envelope(i / samples.length);
    peak = Math.max(peak, Math.abs(samples[i]));
  }
  for (let i = 0; i < samples.length; i++) samples[i] = (samples[i] / peak) * PEAK;
  return samples;
}

/** Whoosh: ruido con paso banda que barre de 400 a 6000 Hz (sube) o de 6000 a 400 Hz (baja); envolvente sen^1,5. */
export function whooshWav({ seconds = 0.6, rising = true, seed = 1 } = {}) {
  const [a, b] = rising ? [400, 6000] : [6000, 400];
  const samples = bandpassNoise(Math.round(seconds * SAMPLE_RATE), seed, (p) => a * Math.pow(b / a, p), 2.5);
  return wav(shape(samples, (p) => Math.pow(Math.sin(Math.PI * p), 1.5)));
}

/** Brillo del trazo: ruido agudo (3–9 kHz) muy tenue mientras se dibuja una línea; entra y sale suave. */
export function shimmerWav({ seconds = 0.95, seed = 7 } = {}) {
  const samples = bandpassNoise(Math.round(seconds * SAMPLE_RATE), seed, () => 5500, 0.9);
  return wav(shape(samples, (p) => Math.sin(Math.PI * p)));
}

/** Pop: seno con una leve caída de tono y decaimiento de ~25 ms (§10 del md). */
export function popWav({ seconds = 0.12 } = {}) {
  const n = Math.round(seconds * SAMPLE_RATE);
  const out = new Float64Array(n);
  let phase = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SAMPLE_RATE;
    phase += (2 * Math.PI * (900 - 3500 * t)) / SAMPLE_RATE; // de 900 Hz hacia abajo
    out[i] = Math.sin(phase) * Math.exp(-t / 0.025);
  }
  return wav(shape(out, () => 1));
}

/** Polvo: ruido agudo que sube y se apaga despacio (la vaporización). */
export function dustWav({ seconds = 0.8, seed = 21 } = {}) {
  const samples = bandpassNoise(Math.round(seconds * SAMPLE_RATE), seed, () => 3500, 0.7);
  return wav(shape(samples, (p) => Math.pow(Math.sin(Math.PI * Math.min(1, p * 0.5 + 0.15)), 1) * Math.exp(-3 * p)));
}

/** Crujido: 22 clics de ruido de banda ancha repartidos en 0,25 s (§10 del md). */
export function crackWav({ seconds = 0.3, seed = 31 } = {}) {
  const n = Math.round(seconds * SAMPLE_RATE);
  const rand = mulberry32(seed);
  const out = new Float64Array(n);
  for (let k = 0; k < 22; k++) {
    const start = Math.floor(rand() * 0.25 * SAMPLE_RATE);
    const len = Math.floor((0.004 + rand() * 0.01) * SAMPLE_RATE);
    for (let i = 0; i < len && start + i < n; i++) out[start + i] += (rand() * 2 - 1) * Math.exp(-i / (len / 4)) * (0.4 + rand() * 0.6);
  }
  return wav(shape(out, () => 1));
}

/** Golpe sordo: ruido de paso bajo (180 Hz) con decaimiento de 70 ms + seno de 55 Hz (§10 del md). */
export function thudWav({ seconds = 0.25, seed = 41 } = {}) {
  const n = Math.round(seconds * SAMPLE_RATE);
  const rand = mulberry32(seed);
  const out = new Float64Array(n);
  const a = (2 * Math.PI * 180) / SAMPLE_RATE;
  let y = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SAMPLE_RATE;
    y += a * ((rand() * 2 - 1) - y);
    out[i] = y * 6 * Math.exp(-t / 0.07) + Math.sin(2 * Math.PI * 55 * t) * Math.exp(-t / 0.12);
  }
  return wav(shape(out, () => 1));
}
