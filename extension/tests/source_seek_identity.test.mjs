import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { contentScriptSource } from "./content_script_loader.mjs";
import { installExtensionScriptLoader } from "./helpers/script-loader.mjs";
import { createSidepanelHarness } from "./sidepanel_test_harness.mjs";

const pageUrl = "https://www.bilibili.com/video/BV1ABCDEF123/?p=1";
const mediaUrl = "https://cdn.example.test/lesson.mp4?token=old";
const closedTabFixture = JSON.parse(await readFile(new URL("./fixtures/source-seek-closed-tab-v1.json", import.meta.url), "utf8"));
Object.freeze(closedTabFixture.activeTab);
Object.freeze(closedTabFixture);
const contentCode = await contentScriptSource();
function video(src = mediaUrl) {
  return {
    currentSrc: src, src: "", currentTime: 3, duration: 120, paused: true,
    ended: false, readyState: 4, videoWidth: 1280, videoHeight: 720,
    play() { throw Error("Seeking must never autoplay"); },
    querySelector() { return null; }, querySelectorAll() { return []; },
    getAttribute() { return ""; },
    getBoundingClientRect() { return { left: 0, top: 0, right: 1280, bottom: 720, width: 1280, height: 720 }; }
  };
}
function contentHarness(url = pageUrl) {
  let selectedVideo = video(), listener;
  const context = vm.createContext({
    console, URL, location: { href: url }, Node: { ELEMENT_NODE: 1 },
    performance: { getEntriesByType() { return []; } },
    document: {
      title: "Synthetic seek fixture", documentElement: { clientWidth: 1440, clientHeight: 900 },
      querySelectorAll(selector) { return selector === "video" ? [selectedVideo].filter(Boolean) : []; }
    },
    chrome: { runtime: { onMessage: { addListener(fn) { listener = fn; } } } },
    setTimeout() { throw Error("Seek must not start timers"); },
    fetch() { throw Error("Seek must not fetch page data"); }
  });
  context.window = context;
  context.innerWidth = 1440; context.innerHeight = 900;
  context.getComputedStyle = () => ({ display: "block", visibility: "visible", opacity: "1" });
  context.addEventListener = () => {};
  vm.runInContext(contentCode, context);
  return {
    context,
    get video() { return selectedVideo; },
    replaceVideo(replacement = video()) { selectedVideo = replacement; },
    active() { return context.activeVideoInfo(); },
    send(message) {
      let result;
      listener(message, {}, value => { result = value; });
      return result;
    }
  };
}
let content = contentHarness();
let tab = { id: 11, url: pageUrl }, tabClosed = false, beforeContent = null, suppressResponse = false, frameContents = null;
const events = {}, calls = [];
const event = name => ({ addListener(fn) { if (name) events[name] = fn; } });
const background = vm.createContext({
  console, URL, Date, setTimeout, clearTimeout,
  fetch() { throw Error("Seek must not contact sites, clients, or models"); },
  chrome: {
    webRequest: { onBeforeSendHeaders: event(), onHeadersReceived: event(), onBeforeRedirect: event(), onCompleted: event(), onErrorOccurred: event() },
    tabs: {
      onRemoved: event(), onActivated: event(), onUpdated: event(),
      async get(id) { calls.push(["get", id]); if (tabClosed) throw Error("Tab closed"); return { ...tab }; },
      async query() { calls.push(["query"]); return [closedTabFixture.activeTab]; },
      async sendMessage(id, message, options) {
        calls.push(["send", id, structuredClone(message), structuredClone(options)]);
        beforeContent?.();
        return suppressResponse ? undefined : (frameContents?.get(options?.frameId) || content).send(message);
      }
    },
    runtime: { onMessage: event("message"), sendMessage() {} },
    webNavigation: { getAllFrames(_details, callback) { callback([...(frameContents?.keys() || [0])].map(frameId => ({ frameId }))); } },
    action: { onClicked: event() },
    scripting: { executeScript() { throw Error("Seek must not collect/inject page evidence"); } },
    cookies: { getAll() { throw Error("Seek must not read cookies"); } }
  }
});
installExtensionScriptLoader(background);
vm.runInContext(await readFile(new URL("../background.js", import.meta.url), "utf8"), background);
const copy = value => JSON.parse(JSON.stringify(value));
function snapshot(frameId = 0) {
  const active = { ...content.active(), frame_id: frameId };
  return {
    ...copy(background.buildSourceIdentity(tab, { page_url: tab.url, active_video: active })),
    page_url: tab.url,
    active_video: { current_src: active.src, frame_id: frameId, frame_url: active.frame_url, seek_token: active.seek_token }
  };
}
let identity = snapshot();
function request(overrides = {}) {
  return { type: "seek-current-video", targetTabId: 11, sourceIdentity: copy(identity), seconds: 42, ...overrides };
}
async function send(overrides = {}) {
  return new Promise(resolve => {
    assert.equal(events.message(request(overrides), {}, resolve), true);
  });
}
function reset() {
  content = contentHarness(); tab = { id: 11, url: pageUrl }; tabClosed = false;
  beforeContent = null; suppressResponse = false; frameContents = null; calls.length = 0; identity = snapshot();
}
function unchanged(result, code = "stale_source_identity") {
  assert.equal(result.ok, false);
  assert.equal(result.code, code);
  assert.equal(content.video?.currentTime ?? 3, 3, "Rejected seek must not mutate playback");
}

// A closed original tab must never redirect to the active tab, even at the same URL.
tabClosed = closedTabFixture.originalTabClosed;
const closedSource = Object.freeze({ ...identity, active_video: Object.freeze({ ...identity.active_video }) });
assert.equal(closedSource.tab_id, closedTabFixture.originalTabId);
assert.equal(closedSource.page_url, closedTabFixture.activeTab.url);
unchanged(await send({ sourceIdentity: closedSource }), closedTabFixture.expectedCode);
assert.deepEqual(calls, [["get", closedTabFixture.originalTabId]]);
reset();
for (const targetTabId of [undefined, null, "11", false, -1, 1.5, 22]) {
  unchanged(await send({ targetTabId }));
}
assert.equal(calls.length, 0, "Invalid/mismatched targets are rejected before any tab lookup");
for (const seconds of [-1, NaN, Infinity, -Infinity, "42", "", null, undefined, true]) {
  unchanged(await send({ seconds }), "invalid_seek_time");
  unchanged(content.send(request({ seconds })), "invalid_seek_time");
}
assert.equal(calls.length, 0);
for (const sourceIdentity of [undefined, {}, { ...identity, tab_id: 22 },
  { ...identity, active_video: { ...identity.active_video, seek_token: "" } },
  { ...identity, active_video: { ...identity.active_video, current_src: "" } }]) {
  unchanged(await send({ sourceIdentity }));
  if (sourceIdentity?.tab_id !== 22) unchanged(content.send(request({ sourceIdentity })));
}
assert.equal(calls.length, 0);

for (const changedUrl of ["https://course.example.test/other", pageUrl.replace("p=1", "p=2"), `${pageUrl}&lesson=2`, `${pageUrl}#part-two`]) {
  reset(); tab.url = changedUrl;
  unchanged(await send());
  assert.deepEqual(calls, [["get", 11]], "Changed page/part is rejected before sending to content");
}
reset(); tab = { id: 22, url: pageUrl };
unchanged(await send(), "source_tab_unavailable");
assert.deepEqual(calls, [["get", 11]]);

// Same URL and platform ID do not excuse a different media source.
reset(); content.video.currentSrc = "https://cdn.example.test/other-lesson.mp4";
unchanged(await send());
reset(); content.video.currentSrc = "";
unchanged(await send());

// Replacing the document or video with an identical URL still invalidates provenance.
reset(); content.replaceVideo();
unchanged(await send());
reset(); content = contentHarness();
unchanged(await send());

// The content listener checks the current URL and element after background lookup.
for (const changedUrl of ["https://course.example.test/other", pageUrl.replace("p=1", "p=2"), `${pageUrl}&lesson=2`]) {
  reset(); beforeContent = () => { content.context.location.href = changedUrl; };
  unchanged(await send());
  assert.equal(calls.filter(call => call[0] === "send").length, 1);
}
reset(); beforeContent = () => { content.replaceVideo(); };
unchanged(await send());
reset(); beforeContent = () => { content.video.currentSrc = "https://cdn.example.test/new.mp4"; };
unchanged(await send());
reset(); beforeContent = () => { content = contentHarness(); };
unchanged(await send());

// Original source succeeds, including zero and supported signed-token renewal.
for (const seconds of [0, 42, 42.25]) {
  reset();
  content.video.currentSrc = "https://cdn.example.test/lesson.mp4?token=renewed&expires=999";
  const result = await send({ seconds });
  assert.equal(result.ok, true);
  assert.equal(content.video.currentTime, seconds);
  assert.equal(content.video.paused, true);
  assert.equal(calls.length, 2);
  const delivery = calls[1];
  assert.equal(delivery[1], 11);
  assert.deepEqual(delivery[3], { frameId: 0 });
  assert.deepEqual(delivery[2].sourceIdentity, identity);
}
// Generic direct, HLS and blob players retain their existing explicit seek behavior.
for (const src of [mediaUrl, "https://cdn.example.test/lesson.m3u8?signature=old", "blob:https://course.example.test/synthetic-media"]) {
  reset(); tab.url = "https://course.example.test/lesson"; content.context.location.href = tab.url;
  content.video.currentSrc = src; identity = snapshot();
  assert.equal((await send()).ok, true);
  assert.equal(content.video.currentTime, 42);
  assert.equal(content.video.paused, true);
}
reset(); suppressResponse = true;
unchanged(await send(), "seek_unconfirmed");

// Embedded video is targeted only in its recorded frame, with its own URL/token.
reset(); content = contentHarness("https://player.example.test/course?part=1"); identity = snapshot(7);
assert.equal((await send()).ok, true);
assert.deepEqual(calls[1][3], { frameId: 7 });
content.video.currentTime = 3; content.context.location.href = "https://player.example.test/course?part=2";
unchanged(await send());

// Exercise the real sidepanel producer, including tab ID 0 and source frame metadata.
reset();
const sourceContext = {
  tab: { id: 0, url: pageUrl, title: "Synthetic lesson" },
  page: { page_url: pageUrl, seek_token: content.active().seek_token, active_video: { ...content.active(), frame_id: 7, frame_url: "https://player.example.test/course?part=1" },
    browser_subtitles: [{ start: 0, end: 120, text: "Synthetic subtitle" }] }, resources: []
};
let produced;
const panel = await createSidepanelHarness({ contexts: [sourceContext], beforeLoad(context) {
  const original = context.chrome.runtime.sendMessage;
  context.chrome.runtime.sendMessage = async message => {
    if (message.type === "seek-current-video") { produced = copy(message); return { ok: true }; }
    return original(message);
  };
} });
await panel.context.seekSourceVideo(12);
assert.deepEqual(Object.keys(produced.sourceIdentity).sort(), ["active_video", "canonical_page_url", "page_url", "platform_video_id", "tab_id"]);
assert.equal(produced.targetTabId, 0);
assert.equal(produced.seconds, 12);
assert.equal(produced.sourceIdentity.tab_id, 0);
assert.equal(produced.sourceIdentity.page_url, pageUrl);
assert.equal(produced.sourceIdentity.canonical_page_url, pageUrl.replace("/?", "?"));
assert.equal(produced.sourceIdentity.platform_video_id, "BV1ABCDEF123");
assert.deepEqual(produced.sourceIdentity.active_video, {
  current_src: mediaUrl, frame_id: 7, frame_url: "https://player.example.test/course?part=1", seek_token: sourceContext.page.active_video.seek_token
});
console.log("Seek listener identity: exact tab, page/part/frame/media, replacement/navigation races, invalid time, token renewal and sidepanel provenance pass");

// Actual content snapshot -> background frame aggregation -> sidepanel -> seek.
// The opaque token stays outside active_video so backend handoffs cannot persist it.
reset();
tab.url = "https://course.example.test/lesson";
const topFrame = contentHarness(tab.url); topFrame.replaceVideo(null);
content = contentHarness("https://player.example.test/course?part=1");
frameContents = new Map([[0, topFrame], [7, content]]);
const storageWrites = [], backendBodies = [];
background.chrome.storage = { local: {
  async get() { return {}; }, async set(value) { storageWrites.push(copy(value)); }, async remove() {}
} };
const dispatch = message => new Promise(resolve => events.message(message, {}, resolve));
const aggregated = await dispatch({ type: "get-current-context", targetTabId: 11 });
assert.equal(aggregated.tab.id, 11);
assert.equal(aggregated.page.active_video.frame_id, 7);
assert.equal(aggregated.page.active_video.frame_url, content.context.location.href);
assert.equal(aggregated.page.seek_token, content.active().seek_token);
assert.equal(Object.hasOwn(aggregated.page.active_video, "seek_token"), false);
let actualSeekResult;
const actualPanel = await createSidepanelHarness({ contexts: [aggregated], beforeLoad(context) {
  const original = context.chrome.runtime.sendMessage;
  context.chrome.runtime.sendMessage = async message => {
    if (message.type === "seek-current-video") return (actualSeekResult = await dispatch(message));
    return original(message);
  };
} });
await actualPanel.context.seekSourceVideo(17);
assert.equal(actualSeekResult.ok, true);
assert.equal(content.video.currentTime, 17);
assert.equal(calls.filter(call => call[0] === "send").at(-1)[3].frameId, 7);

// Exercise all normal active-video backend payload builders using offline adapters.
background.chrome.cookies.getAll = async () => [];
background.fetch = async (url, options = {}) => {
  if (options.body) backendBodies.push(JSON.parse(options.body));
  return { ok: true, json: async () => String(url).includes("/api/tasks/") ? { task_id: "synthetic-seek-task" } : { report: { ok: true } } };
};
await dispatch({ type: "start-current-task", targetTabId: 11, page: aggregated.page, resources: [], mode: "subtitle_only" });
await dispatch({ type: "preflight-current-page", targetTabId: 11, page: aggregated.page, resources: [] });
await background.__learnnoteE2E.startCurrentPageTaskForTab(11, "http://127.0.0.1:8765", [], "subtitle_only");
assert.equal(backendBodies.length, 3);
await new Promise(setImmediate);
assert.ok(storageWrites.length > 0, "Exercise real capture persistence in the offline adapter");
for (const value of [...backendBodies, ...storageWrites]) {
  assert.equal(JSON.stringify(value).includes("seek_token"), false);
  assert.equal(JSON.stringify(value).includes(aggregated.page.seek_token), false);
}
console.log("Actual frame aggregation preserves seek provenance; backend task/preflight/E2E payloads and capture storage exclude the opaque token");
