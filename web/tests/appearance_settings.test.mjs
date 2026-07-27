import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const html = fs.readFileSync(path.join(root, "web", "index.html"), "utf8");
const app = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");
const css = fs.readFileSync(path.join(root, "web", "mature.css"), "utf8");

test("appearance settings expose a live preview and all supported choices", () => {
  assert.match(html, /class="appearance-preview"/);
  for (const value of ["90", "100", "110", "compact", "standard", "large", "system", "light", "dark", "teal", "ocean", "forest", "graphite"]) {
    assert.match(html, new RegExp(`data-value="${value}"`));
  }
});

test("appearance choices map to final CSS tokens", () => {
  for (const selector of [
    'body[data-color-theme="ocean"]',
    'body[data-color-theme="forest"]',
    'body[data-color-theme="graphite"]',
    'body[data-text-size="compact"]',
    'body[data-text-size="large"]',
    'body[data-ui-density="90"]',
    'body[data-ui-density="110"]',
    "body.theme-dark"
  ]) {
    assert.ok(css.includes(selector), `missing CSS contract for ${selector}`);
  }
  assert.match(css, /--appearance-accent:/);
  assert.match(css, /--appearance-row-height:/);
  assert.match(css, /@media \(min-width: 681px\) and \(max-width: 900px\)/);
  assert.match(css, /margin-left: var\(--mature-nav\)/);
});

test("system theme updates while the client is open", () => {
  assert.match(app, /matchMedia\?\.\("\(prefers-color-scheme: dark\)"\)/);
  assert.match(app, /systemThemeMedia\?\.addEventListener\?\.\("change"/);
  assert.match(app, /appSettings\.theme === "system"/);
});
