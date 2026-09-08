import assert from "node:assert/strict";
import { createSidepanelHarness, videoContext } from "./sidepanel_test_harness.mjs";

const live = { service: "learnnote", app_version: "0.2.3", backend_version: "0.2.3", protocol_version: 1 };
const healthByUrl = {};
const reconnect = await createSidepanelHarness({ contexts: [videoContext()], healthByUrl });
assert.equal(reconnect.api.getState().clientConnected, false);
healthByUrl["http://127.0.0.1:8765/health"] = live;
await reconnect.elements.get("#refreshButton").dispatch("click");
assert.equal(reconnect.api.getState().clientConnected, true, "refresh must reconnect an app started after the panel");
assert.equal(reconnect.elements.get("#sendButton").disabled, false);
const countBefore = reconnect.fetchCalls.length;
await Promise.all([reconnect.api.checkClient(), reconnect.api.checkClient(), reconnect.api.checkClient()]);
assert.equal(reconnect.fetchCalls.length - countBefore, 1, "overlapping connection checks share one health request");

const existingUrl = "http://127.0.0.1:8765/?view=old#task/original";
const reuse = await createSidepanelHarness({ contexts: [videoContext()], tabs: [{ id: 8, url: existingUrl }] });
await reuse.api.openClient();
assert.equal(reuse.updatedTabs[0].url, existingUrl, "opening the workbench should focus it without changing its document or source");
await reuse.api.openClient("task", "new-task", "transcript");
assert.equal(reuse.updatedTabs[1].url, "http://127.0.0.1:8765/?view=old#task/new-task?tab=transcript");
await reuse.api.openClient("settings", "old-task");
assert.equal(reuse.updatedTabs[2].url, "http://127.0.0.1:8765/?view=old#settings");
assert.equal(reuse.openedTabs.length, 0);

const exportTab = await createSidepanelHarness({ contexts: [videoContext()], tabs: [{ id: 8, url: "http://127.0.0.1:8765/api/tasks/test/exports/markdown" }] });
await Promise.all([exportTab.api.openClient(), exportTab.api.openClient()]);
assert.equal(exportTab.updatedTabs.length, 0, "downloads and API pages must not be overwritten");
assert.equal(exportTab.openedTabs.length, 1, "repeated open clicks create only one workbench tab");

const wrongProduct = await createSidepanelHarness({ contexts: [videoContext()], health: { ...live, service: "other-app" } });
assert.equal(wrongProduct.api.getState().clientConnected, false);
const legacy = await createSidepanelHarness({ contexts: [videoContext()], health: { ...live, service: undefined, task_schema_version: 1, local_asr_available: true } });
assert.equal(legacy.api.getState().clientConnected, true, "previous LearnNote health contract remains compatible");

const pinnedHealth = { "http://127.0.0.1:8765/health": live };
const pinned = await createSidepanelHarness({ contexts: [videoContext()], healthByUrl: pinnedHealth, tabs: [{ id: 9, url: "http://127.0.0.1:18898/" }] });
await pinned.api.sendToClient();
delete pinnedHealth["http://127.0.0.1:8765/health"];
pinnedHealth["http://127.0.0.1:18898/health"] = live;
assert.equal(await pinned.api.checkClient(), false);
assert.equal(pinned.api.getState().backendUrl, "http://127.0.0.1:8765", "an existing task must stay associated with its own data library");
assert.match(pinned.elements.get("#connectionTitle").textContent, /任务所在/);

const home = videoContext();
home.page.page_url = home.tab.url = "https://www.bilibili.com/";
const homepage = await createSidepanelHarness({ contexts: [home] });
assert.equal(await homepage.api.sendToClient(), false);
assert.equal(homepage.elements.get("#sendButton").getAttribute("aria-busy"), "false");
assert.equal(homepage.sentMessages.some(message => message.type === "start-current-task"), false);

const subtitles = videoContext();
subtitles.page.browser_subtitles = Array.from({ length: 12 }, (_, i) => ({ start: i * 55, end: i * 55 + 50, text: `字幕 ${i}` }));
subtitles.resources = [];
delete subtitles.page.active_video.src;
const textOnly = await createSidepanelHarness({ contexts: [subtitles] });
assert.equal(textOnly.elements.get("#sendButton").disabled, false, "available full subtitles do not require downloadable media");
assert.equal(await textOnly.elements.get("#sendButton").dispatch("click"), true);
assert.equal(textOnly.sentMessages.find(message => message.type === "start-current-task").mode, "subtitle_only");
await new Promise(resolve => setTimeout(resolve, 20));

let finishOldPoll;
const oldPoll = new Promise(resolve => { finishOldPoll = resolve; });
const switched = videoContext({ bvid: "BV9NEWVIDEO99", title: "新视频" });
const stale = await createSidepanelHarness({
  contexts: [subtitles, subtitles, switched],
  fetchOverride: url => /\/api\/tasks\/[^/]+$/.test(url) ? oldPoll : null
});
await stale.api.sendToClient();
await stale.api.collectContext(true);
const messageBefore = stale.elements.get("#quickResultStatus").textContent;
finishOldPoll({ ok: true, json: async () => ({ task: { id: "abc123def456", status: "failed", message: "旧任务失败" } }) });
await new Promise(resolve => setTimeout(resolve, 20));
assert.equal(stale.elements.get("#quickResultStatus").textContent, messageBefore, "old task responses cannot overwrite the new source");
assert.equal(stale.api.getState().currentTaskId, "");

console.log("Reconnect, real click subtitle path, safe workbench reuse, source isolation, and recovery passed");
