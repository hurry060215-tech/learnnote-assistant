import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const settings = fs.readFileSync(path.join(root, "web", "desk-settings.js"), "utf8");
const css = fs.readFileSync(path.join(root, "web", "desk.css"), "utf8");
const tools = fs.readFileSync(path.join(root, "web", "desk-tools.js"), "utf8");

test("settings exposes the explainable local-first model route", () => {
  assert.match(settings, /model-route-panel/);
  assert.match(settings, /\/api\/model\/route/);
  assert.match(settings, /item.network === "required"/);
  assert.match(settings, /blocking_reasons/);
  assert.match(css, /\.model-route-list/);
});

test("course comparison keeps a visual relationship view and an evidence list", () => {
  assert.match(tools, /function relationshipGraph\(result\)/);
  assert.match(tools, /relationship-graph/);
  assert.match(tools, /evidence_ids/);
  assert.match(tools, /关系列表/);
});
