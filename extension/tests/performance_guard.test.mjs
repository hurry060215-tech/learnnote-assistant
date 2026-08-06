import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const manifest = JSON.parse(await readFile(new URL("../manifest.json", import.meta.url), "utf8"));
const background = await readFile(new URL("../background.js", import.meta.url), "utf8");
const content = await readFile(new URL("../content.js", import.meta.url), "utf8");

assert.equal(
  manifest.content_scripts.some(script => script.js?.includes("page_hook.js")),
  false,
  "the invasive MAIN-world hook must never run automatically on every page"
);
assert.match(background, /types:\s*\["media",\s*"xmlhttprequest"\]/);
assert.doesNotMatch(background, /files:\s*\["page_hook\.js"\]/);
assert.match(content, /const PERIODIC_SCAN_MS = 60000;/);
assert.match(content, /const selector = "video,source,track,iframe";/);
assert.match(content, /attributeFilter:\s*\["src",\s*"currentSrc",\s*"type"\]/);
assert.doesNotMatch(content, /for \(const host of safeQueryAll\(node, "\*"\)\)/);
