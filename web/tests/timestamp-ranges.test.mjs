import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
const source = readFileSync(new URL("../desk-api.js", import.meta.url), "utf8");
const { timestampRanges } = await import(
  "data:text/javascript;base64," + Buffer.from(source).toString("base64")
);
test("MiMo bracket ranges preserve exact visible copy and seek to first timestamp", () => {
  const text = "需要换乘专属列车（[00:53 – 01:00]），再抵达酒店。";
  assert.deepEqual(timestampRanges(text), [
    { index: text.indexOf("["), label: "[00:53 – 01:00]", start: 53, end: 60 },
  ]);
});
test("multiple bracket ranges and hour timestamps retain independent text offsets", () => {
  const result = timestampRanges("A [1:02:03-1:04:05] B [12:10 — 12:40]");
  assert.equal(result.length, 2);
  assert.equal(result[0].start, 3723);
  assert.equal(result[1].start, 730);
});
test("invalid seconds, reversed ranges, and ordinary bracket text stay untouched", () => {
  assert.deepEqual(
    timestampRanges(
      "[00:99 – 01:00] [02:00 – 01:00] [参考资料] [1:60:00-2:00:00]",
    ),
    [],
  );
});
