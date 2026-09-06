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

assert.doesNotMatch(html, /href="[^" ]*classic\.html/);
const tools=readFileSync(new URL("../desk-tools.js",import.meta.url),"utf8");
assert.doesNotMatch(tools,/href="[^" ]*classic\.html/);
const apiSource=readFileSync(new URL("../desk-api.js",import.meta.url),"utf8");
const apiModule=await import("data:text/javascript;base64,"+Buffer.from(apiSource).toString("base64"));
globalThis.location={origin:"http://127.0.0.1:18782"};
assert.equal(apiModule.taskAsset("http://127.0.0.1:8765/api/tasks/abc/frames/a.jpg","abc"),"/api/tasks/abc/frames/a.jpg");
assert.equal(apiModule.taskAsset("https://tracker.example/pixel.png","abc"),"");
assert.equal(apiModule.taskAsset("/api/tasks/other/frames/a.jpg","abc"),"");
