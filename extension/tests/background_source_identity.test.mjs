import { installExtensionScriptLoader } from "./helpers/script-loader.mjs";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function listener(name = "") {
  return { addListener(callback) { if (name) listeners[name] = callback; } };
}

const listeners = {};
const requestBodies = [];
let activeBvid = "BV1ABCDEF123";
let mediaToken = "one";
let pageTitleSuffix = "";
let taskFailuresRemaining = 0;
const context = {
  console,
  Date,
  URL,
  fetch: async (url, options = {}) => {
    requestBodies.push({ url: String(url), body: JSON.parse(String(options.body || "{}")) });
    if (String(url).includes("/api/tasks/from-current-page") && taskFailuresRemaining > 0) {
      taskFailuresRemaining -= 1;
      throw new Error("temporary backend disconnect");
    }
    return { ok: true, json: async () => ({ task_id: "abc123def456" }) };
  },
  setTimeout,
  clearTimeout,
  chrome: {
    webRequest: {
      onBeforeSendHeaders: listener(), onHeadersReceived: listener(), onBeforeRedirect: listener(),
      onCompleted: listener(), onErrorOccurred: listener()
    },
    tabs: {
      onRemoved: listener(), onActivated: listener(), onUpdated: listener(),
      async query() { return []; },
      async get(tabId) { return { id: tabId, title: `Video ${activeBvid}${pageTitleSuffix}`, url: `https://www.bilibili.com/video/${activeBvid}/` }; },
      async sendMessage() {
        const url = `https://www.bilibili.com/video/${activeBvid}/`;
        return {
          title: `Video ${activeBvid}${pageTitleSuffix}`,
          page_url: url,
          page_text: "",
          active_video: { src: `https://cdn.example.com/${activeBvid}.mp4?token=${mediaToken}`, duration: 120, paused: false },
          browser_subtitles: [],
          resources: [{ url: `https://cdn.example.com/${activeBvid}.mp4?token=${mediaToken}`, kind: "video", score: 100 }]
        };
      }
    },
    action: { onClicked: listener() },
    runtime: { getManifest() { return { version: "0.2.14" }; }, sendMessage() {}, onMessage: listener("runtimeMessage") },
    webNavigation: { getAllFrames(_details, callback) { callback([{ frameId: 0 }]); } },
    sidePanel: { open() {} },
    scripting: { executeScript() {} },
    storage: { local: { async get() { return {}; }, async set() {}, async remove() {} } },
    cookies: { async getAll() { return []; } }
  }
};

vm.createContext(context);
installExtensionScriptLoader(context);
vm.runInContext(await readFile(new URL("../background.js", import.meta.url), "utf8"), context);

const collect = () => new Promise(resolve => listeners.runtimeMessage({ type: "get-current-context", targetTabId: 9 }, {}, resolve));
const initial = await collect();
const expectedIdentity = context.buildSourceIdentity(initial.tab, initial.page, initial.resources, Date.UTC(2026, 6, 22));

const accepted = await new Promise(resolve => listeners.runtimeMessage({
  type: "start-current-task",
  targetTabId: 9,
  backendUrl: "http://127.0.0.1:8765",
  sourceIdentity: expectedIdentity,
  handoffId: "ln-source-test-0001",
  defer: true,
  page: initial.page,
  resources: initial.resources,
  mode: "video"
}, {}, resolve));

assert.equal(accepted.task_id, "abc123def456");
const taskRequests = () => requestBodies.filter(item => item.url.includes("/api/tasks/from-current-page"));
assert.equal(taskRequests().length, 1);
assert.equal(taskRequests()[0].url, "http://127.0.0.1:8765/api/tasks/from-current-page?defer=true");
assert.equal(taskRequests()[0].body.source_identity.tab_id, 9);
assert.equal(taskRequests()[0].body.source_identity.BVID, "BV1ABCDEF123");
assert.equal(taskRequests()[0].body.source_identity.platform_video_id, "BV1ABCDEF123");
assert.equal(taskRequests()[0].body.handoff_id, "ln-source-test-0001");
assert.equal(taskRequests()[0].body.extension_version, "0.2.14");
assert.equal(taskRequests()[0].body.subtitle_probe.status, "unavailable");

mediaToken = "renewed";
pageTitleSuffix = " - updated";
const renewed = await new Promise(resolve => listeners.runtimeMessage({
  type: "start-current-task",
  targetTabId: 9,
  backendUrl: "http://127.0.0.1:8765",
  sourceIdentity: expectedIdentity,
  handoffId: "ln-source-test-0001",
  defer: true,
  page: initial.page,
  resources: initial.resources,
  mode: "video"
}, {}, resolve));
assert.equal(renewed.task_id, "abc123def456", "title and expiring token changes must remain the same source");
assert.equal(taskRequests().length, 2);

taskFailuresRemaining = 1;
const retried = await new Promise(resolve => listeners.runtimeMessage({
  type: "start-current-task",
  targetTabId: 9,
  backendUrl: "http://127.0.0.1:8765",
  sourceIdentity: expectedIdentity,
  handoffId: "ln-network-retry-0001",
  defer: true,
  page: initial.page,
  resources: initial.resources,
  mode: "video"
}, {}, resolve));
assert.equal(retried.task_id, "abc123def456");
assert.equal(taskRequests().length, 4, "one transient network failure should produce one bounded retry");
assert.equal(taskRequests()[2].body.handoff_id, taskRequests()[3].body.handoff_id);

activeBvid = "BV9SWITCHED99";
const rejected = await new Promise(resolve => listeners.runtimeMessage({
  type: "start-current-task",
  targetTabId: 9,
  backendUrl: "http://127.0.0.1:8765",
  sourceIdentity: expectedIdentity,
  defer: true,
  page: initial.page,
  resources: initial.resources,
  mode: "video"
}, {}, resolve));

assert.equal(rejected.code, "stale_source_identity");
assert.match(rejected.error, /页面或播放内容已切换/);
assert.equal(rejected.source_identity.BVID, "BV9SWITCHED99");
assert.equal(taskRequests().length, 4, "stale source must be rejected before another backend task creation");

activeBvid = "BV1ABCDEF123";
const captionTask = await new Promise(resolve => listeners.runtimeMessage({
  type: "start-current-task", targetTabId: 9,
  backendUrl: "http://127.0.0.1:8765", sourceIdentity: expectedIdentity,
  page: initial.page, resources: [], mode: "subtitle_only",
  options: { content_mode: "subtitles" }
}, {}, resolve));
assert.equal(captionTask.task_id, "abc123def456");
assert.equal(taskRequests().at(-1).body.resources.length, 0, "background must not re-add cached video resources to a subtitle-only handoff");
assert.equal(taskRequests().at(-1).body.cookies.length, 0);
assert.equal(taskRequests().at(-1).body.options.content_mode, "subtitles");

activeBvid = "BV9PROBE0001";
context.chrome.scripting.executeScript = async () => [{ result: {
  status: "ready", language: "zh-CN", duration: 120,
  cues: [{ start: 0, end: 10, text: "Synthetic subtitle" }]
} }];
await collect(); // Reset the previous page's capture context before probing.
const probeContext = await collect();
assert.equal(probeContext.page.subtitle_probe.cache_hit, false);
const probeIdentity = context.buildSourceIdentity(probeContext.tab, probeContext.page, probeContext.resources);
await new Promise(resolve => listeners.runtimeMessage({
  type: "start-current-task", targetTabId: 9, sourceIdentity: probeIdentity,
  resources: [], mode: "subtitle_only", defer: true
}, {}, resolve));
const probe = taskRequests().at(-1).body.subtitle_probe;
assert.deepEqual(Object.keys(probe).sort(), ["cache_hit", "cue_count", "elapsed_ms", "language", "status"]);
assert.equal(probe.status, "ready");
assert.equal(probe.language, "zh-CN");
assert.equal(probe.cue_count, 1);
assert.equal(probe.cache_hit, true);
assert.ok(Number.isFinite(probe.elapsed_ms) && probe.elapsed_ms >= 0);
assert.equal(taskRequests().at(-1).body.extension_version, "0.2.14");
await context.__learnnoteE2E.startCurrentPageTaskForTab(9, "http://127.0.0.1:8765", [], "subtitle_only");
assert.deepEqual(taskRequests().at(-1).body.subtitle_probe, probe);
assert.equal(taskRequests().at(-1).body.extension_version, "0.2.14");
