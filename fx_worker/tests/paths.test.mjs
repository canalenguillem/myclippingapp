import assert from "node:assert/strict";
import { test } from "node:test";
import { PathError, resolveInMedia } from "../src/paths.mjs";

test("resuelve dentro de MEDIA_DIR", () => {
  assert.equal(resolveInMedia("/media", "u1/p1/a.mp4"), "/media/u1/p1/a.mp4");
});

test("rechaza lo que se sale de MEDIA_DIR", () => {
  for (const bad of ["../etc/passwd", "u1/../../etc/passwd", "/etc/passwd", "u1/../../media2/x.mp4"]) {
    assert.throws(() => resolveInMedia("/media", bad), PathError, bad);
  }
});

test("un directorio hermano con el mismo prefijo no cuela", () => {
  assert.throws(() => resolveInMedia("/media", "../media2/x.mp4"), PathError);
});
