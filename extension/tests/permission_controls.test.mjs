import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const sidepanel = await readFile(new URL("../sidepanel.html", import.meta.url), "utf8");
const sidepanelScript = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
const background = await readFile(new URL("../background.js", import.meta.url), "utf8");
const en = JSON.parse(await readFile(new URL("../_locales/en/messages.json", import.meta.url), "utf8"));
const zh = JSON.parse(await readFile(new URL("../_locales/zh_CN/messages.json", import.meta.url), "utf8"));

assert.match(sidepanel, /id="permissionDetails"/);
assert.match(sidepanel, /id="permissionList"/);
assert.match(sidepanel, /id="permissionStatus"/);
assert.match(sidepanelScript, /chrome\.permissions\.getAll/);
assert.match(sidepanelScript, /chrome\.permissions\.remove/);
assert.match(sidepanelScript, /revoke-site-permission/);
assert.match(sidepanelScript, /sitePermissionPattern/);
assert.match(sidepanelScript, /site_permission_data_flow/);
assert.match(sidepanelScript, /site-permission-revoked/);
assert.match(background, /revoke-site-permission/);
assert.match(background, /revokeSitePermissionCaches/);
assert.match(background, /site-permission-revoked/);
assert.match(background, /sitePermissionGrantedForUrl/);
assert.match(background, /if \(!captureActive\(tabId\)\)/);
assert.match(background, /activeCaptureUntilByTab\.delete/);
assert.match(background, /clearCaptureLog\(tab\.id\)/);
assert.match(zh.site_permission_data_flow.message, /仅字幕模式不读取 Cookie/);
assert.match(zh.site_permission_data_flow.message, /Cookie 不会发送给模型/);
assert.match(en.site_permission_data_flow.message, /subtitle-only mode does not read cookies/i);
assert.match(en.site_permission_data_flow.message, /never to a model/i);
assert.match(zh.incompatible_client_detail.message, /扩展协议 \{extension\}/);
assert.match(en.incompatible_client_detail.message, /Extension protocol \{extension\}/);

console.log("Progressive site permission list, revoke and cache cleanup contracts pass");
