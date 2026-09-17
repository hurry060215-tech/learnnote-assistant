import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const sidepanel = await readFile(new URL("../sidepanel.html", import.meta.url), "utf8");
const sidepanelScript = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
const background = await readFile(new URL("../background.js", import.meta.url), "utf8");

assert.match(sidepanel, /id="permissionDetails"/);
assert.match(sidepanel, /id="permissionList"/);
assert.match(sidepanel, /id="permissionStatus"/);
assert.match(sidepanelScript, /chrome\.permissions\.getAll/);
assert.match(sidepanelScript, /chrome\.permissions\.remove/);
assert.match(sidepanelScript, /revoke-site-permission/);
assert.match(sidepanelScript, /sitePermissionPattern/);
assert.match(background, /revoke-site-permission/);
assert.match(background, /revokeSitePermissionCaches/);
assert.match(background, /activeCaptureUntilByTab\.delete/);
assert.match(background, /clearCaptureLog\(tab\.id\)/);

console.log("Progressive site permission list, revoke and cache cleanup contracts pass");
