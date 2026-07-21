import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const html = await readFile(new URL("../sidepanel.html", import.meta.url), "utf8");
const css = await readFile(new URL("../sidepanel.css", import.meta.url), "utf8");

assert.match(html, /id="backendStatus"[^>]*data-connection-state="checking"[^>]*aria-live="polite"/);
assert.match(html, /id="activeVideo"[^>]*aria-live="polite"/);
assert.match(html, /id="summarizeButton"[\s\S]*?发送到 LearnNote[\s\S]*?<\/button>/);
assert.doesNotMatch(html, /id="openClientPrimaryButton"/);
assert.doesNotMatch(html, /发送到客户端总结/);
assert.equal([...html.matchAll(/sidepanel\.(?:css|js)\?v=20260721-v0132/g)].length, 2);

assert.match(css, /data-panel-mode="study"[^\n]*\.current-card #activeVideo\s*\{\s*display: grid;/);
assert.match(css, /#backendStatus\[data-connection-state="connected"\]::before/);
assert.match(css, /\.progress-panel,[\s\S]*?\.result-panel,[\s\S]*?display: none !important;/);
