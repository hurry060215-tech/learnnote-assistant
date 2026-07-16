import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const manifest = JSON.parse(await readFile(new URL("../manifest.json", import.meta.url), "utf8"));

assert.equal(manifest.manifest_version, 3);
assert.deepEqual(new Set(manifest.permissions), new Set([
  "activeTab",
  "tabs",
  "scripting",
  "webRequest",
  "webNavigation",
  "cookies",
  "storage",
  "sidePanel",
  "downloads"
]));

const hostPermissions = new Set(manifest.host_permissions || []);
assert.equal(hostPermissions.has("<all_urls>"), true);
assert.equal(hostPermissions.has("http://127.0.0.1/*"), true);
assert.equal(hostPermissions.has("http://localhost/*"), true);
assert.equal(hostPermissions.has("http://127.0.0.1:8765/*"), false);

assert.equal(manifest.side_panel.default_path, "sidepanel.html");
assert.equal(manifest.content_scripts.some(item => item.js?.includes("page_hook.js") && item.all_frames === true && item.world === "MAIN"), true);
assert.equal(manifest.content_scripts.some(item => item.js?.includes("content.js") && item.all_frames === true), true);
for (const script of manifest.content_scripts) {
  assert.equal(script.match_about_blank, true);
  assert.equal(script.match_origin_as_fallback, true);
}
