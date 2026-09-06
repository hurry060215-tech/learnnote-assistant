import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const css = readFileSync(new URL("../desk.css", import.meta.url), "utf8");
assert.match(html, /desk\.css/);
assert.match(html, /desk\.js/);
assert.doesNotMatch(html, /src="[^" ]*\/app\.js/);
assert.doesNotMatch(
  html,
  /href="[^" ]*\/(styles|mature|editorial|experience)\.css/,
);
for (const id of [
  "document",
  "newNote",
  "noteText",
  "sourcePanel",
  "annotationForm",
  "reviewDialog",
])
  assert.match(html, new RegExp(`id="${id}"`));
assert.match(css, /:focus-visible/);
assert.match(html, /aria-live="polite"/);
console.log("New workspace owns its layout and core interaction surfaces");
