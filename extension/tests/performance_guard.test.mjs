import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const manifest = JSON.parse(await readFile(new URL("../manifest.json", import.meta.url), "utf8"));
const background = await readFile(new URL("../background.js", import.meta.url), "utf8");
const content = await readFile(new URL("../content.js", import.meta.url), "utf8");

assert.equal(
  (manifest.content_scripts || []).length,
  0,
  "LearnNote must not inject scripts until the user opens the Side Panel"
);
assert.match(background, /types:\s*\["media",\s*"xmlhttprequest"\]/);
assert.match(background, /const ACTIVE_CAPTURE_TTL_MS = 5 \* 60 \* 1000;/);
assert.match(background, /if \(captureActive\(details\.tabId\)\)/);
assert.match(background, /const BACKEND_HEARTBEAT_PERIOD_MINUTES = 2;/);
assert.doesNotMatch(background, /files:\s*\["page_hook\.js"\]/);
assert.doesNotMatch(content, /\bstartWatchers\(\);/);
assert.doesNotMatch(content, /setInterval\s*\(/);
assert.match(content, /const selector = "video,source,track,iframe";/);
assert.match(content, /attributeFilter:\s*\["src",\s*"currentSrc",\s*"type"\]/);
assert.doesNotMatch(content, /for \(const host of safeQueryAll\(node, "\*"\)\)/);
