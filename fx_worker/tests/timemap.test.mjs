import assert from "node:assert/strict";
import { test } from "node:test";
import { makeTimeMap, mapIntervals } from "../src/timemap.mjs";

test("sin cortinilla el mapa es la identidad", () => {
  const m = makeTimeMap(undefined);
  assert.equal(m.out(12.3), 12.3);
  assert.equal(m.total(30), 30);
  assert.equal(m.at, null);
});

test("lo posterior a la inserción se retrasa su duración; lo anterior no se mueve", () => {
  const m = makeTimeMap({ at: 5, duration: 3.6 });
  assert.equal(m.out(4.99), 4.99);
  assert.equal(m.out(5), 8.6);
  assert.equal(m.out(10), 13.6);
  assert.equal(m.total(30), 33.6);
});

test("un tramo que cruza la inserción se parte en dos y no cubre la cortinilla", () => {
  const m = makeTimeMap({ at: 5, duration: 3.6 });
  assert.deepEqual(mapIntervals([[1, 2], [4, 7], [6, 8]], m), [[1, 2], [4, 5], [8.6, 10.6], [9.6, 11.6]]);
});
