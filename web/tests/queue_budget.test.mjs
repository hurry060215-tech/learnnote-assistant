import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(new URL("../desk.js", import.meta.url), "utf8");
test("task status includes lane budget and escapes the complete heading", () => {
  const detail = source.slice(source.indexOf("const queueDetail ="), source.indexOf("const raw =", source.indexOf("const queueDetail =")));
  assert.match(detail, /t\.queue\?\.lane_concurrency/);
  assert.match(detail, /t\.options\?\.low_resource_mode/);
  assert.match(detail, /\+ queueDetail \+ budgetDetail/);
  assert.match(source, /<strong>\$\{esc\(title\)\}<\/strong>/);
});
