import assert from "node:assert/strict";
import { test } from "node:test";
import { SAMPLE_RATE, shimmerWav, whooshWav } from "../src/sfx.mjs";

const samples = (buf) => Array.from({ length: (buf.length - 44) / 2 }, (_, i) => buf.readInt16LE(44 + i * 2) / 32768);
const zcr = (xs) => xs.slice(1).filter((x, i) => (x >= 0) !== (xs[i] >= 0)).length / xs.length;

test("WAV válido: PCM de 16 bits, mono, 48 kHz y la duración pedida", () => {
  const b = whooshWav({ seconds: 0.5 });
  assert.equal(b.toString("ascii", 0, 4), "RIFF");
  assert.equal(b.toString("ascii", 8, 16), "WAVEfmt ");
  assert.deepEqual([b.readUInt16LE(20), b.readUInt16LE(22), b.readUInt32LE(24), b.readUInt16LE(34)], [1, 1, SAMPLE_RATE, 16]);
  assert.equal(b.readUInt32LE(40), 0.5 * SAMPLE_RATE * 2);
  assert.equal(b.length, 44 + b.readUInt32LE(40));
});

test("determinista: misma semilla, mismos bytes; otra semilla, otros", () => {
  assert.ok(whooshWav({ seed: 3 }).equals(whooshWav({ seed: 3 })));
  assert.ok(!whooshWav({ seed: 3 }).equals(whooshWav({ seed: 4 })));
  assert.ok(shimmerWav().equals(shimmerWav()));
});

test("niveles: no está vacío, el pico queda por debajo de 0,55 y la envolvente arranca y acaba en silencio", () => {
  for (const buf of [whooshWav(), shimmerWav()]) {
    const xs = samples(buf);
    const peak = Math.max(...xs.map(Math.abs));
    assert.ok(peak > 0.3 && peak <= 0.55, `pico ${peak}`);
    const edge = Math.max(...xs.slice(0, 200).map(Math.abs), ...xs.slice(-200).map(Math.abs));
    assert.ok(edge < 0.05, `bordes ${edge}`);
  }
});

test("el whoosh que sube tiene más agudos al final y el que baja, al principio", () => {
  const up = samples(whooshWav({ seconds: 0.6, rising: true }));
  const down = samples(whooshWav({ seconds: 0.6, rising: false }));
  const third = Math.floor(up.length / 3);
  assert.ok(zcr(up.slice(2 * third - 2000, 2 * third + 4000)) > 2 * zcr(up.slice(0, third - 2000)), "sube");
  assert.ok(zcr(down.slice(0, third + 2000)) > 2 * zcr(down.slice(2 * third)), "baja");
});

test("el brillo es agudo (muchos más cruces por cero que un whoosh grave)", () => {
  const shimmer = samples(shimmerWav());
  const lowStart = samples(whooshWav({ rising: true })).slice(0, 8000);
  assert.ok(zcr(shimmer) > 3 * zcr(lowStart));
});
