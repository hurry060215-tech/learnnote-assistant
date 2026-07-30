import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const app = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");

test("result popovers close after selection, outside clicks, and Escape", () => {
  assert.match(app, /resultToolTabs:\s*document\.querySelector\("details\.result-tool-tabs"\)/);
  assert.match(app, /function closeResultMenus\(except = null\)/);
  assert.match(app, /const parentMenu = tab\.closest\?\.\("details\.result-tool-tabs"\)/);
  assert.match(app, /if \(parentMenu\) parentMenu\.open = false/);
  assert.match(app, /event\.target\?\.closest\?\.\("#resultMoreActions, details\.result-tool-tabs"\)/);
  assert.match(app, /if \(event\.key !== "Escape"\) return;\s*closeResultMenus\(\)/);
});
