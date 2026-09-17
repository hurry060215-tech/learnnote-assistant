import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const manifest = JSON.parse(await readFile(new URL("../manifest.json", import.meta.url), "utf8"));

assert.equal(manifest.manifest_version, 3);
assert.equal(manifest.default_locale, "zh_CN");
assert.equal(manifest.name, "__MSG_extensionName__");
assert.deepEqual(new Set(manifest.permissions), new Set([
  "activeTab",
  "tabs",
  "scripting",
  "webRequest",
  "webNavigation",
  "cookies",
  "storage",
  "alarms",
  "sidePanel",
  "downloads"
]));

const hostPermissions = new Set(manifest.host_permissions || []);
assert.equal(hostPermissions.has("http://127.0.0.1/*"), true);
assert.equal(hostPermissions.has("http://localhost/*"), true);
assert.equal(hostPermissions.has("http://127.0.0.1:8765/*"), false);
assert.deepEqual(new Set(manifest.optional_host_permissions), new Set(["http://*/*", "https://*/*"]));

assert.equal(manifest.side_panel.default_path, "sidepanel.html");
assert.deepEqual(manifest.content_scripts || [], []);
const sidepanel = await readFile(new URL("../sidepanel.html", import.meta.url), "utf8");
assert.match(sidepanel, /sidepanel\.css\?v=0\.2\.12/);
assert.match(sidepanel, /sidepanel\.js\?v=0\.2\.12/);
