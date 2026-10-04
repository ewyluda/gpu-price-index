// Node parity test: site/tco.js must reproduce the Python reference outputs.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildVsRent } from "../site/tco.js";

const cases = JSON.parse(readFileSync(new URL("./fixtures/tco_cases.json", import.meta.url)));

const close = (actual, expected, path) => {
  if (expected === null || typeof expected !== "object") {
    if (typeof expected === "number") assert.ok(Math.abs(actual - expected) < 0.011, `${path}: ${actual} != ${expected}`);
    else assert.equal(actual, expected, path);
    return;
  }
  for (const [k, v] of Object.entries(expected)) close(actual[k], v, `${path}.${k}`);
};

for (const c of cases) {
  test(`tco parity: ${c.name}`, () => {
    close(buildVsRent(c.assumptions, c.gpu_count, c.utilization, c.rent), c.expected, c.name);
  });
}
