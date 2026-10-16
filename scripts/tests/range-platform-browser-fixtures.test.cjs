/* Contract checks need only Node; these are not browser acceptance evidence. */
const assert = require("node:assert/strict");
const {test} = require("node:test");
const vm = require("node:vm");
const gate = require("../range-platform-browser-acceptance.cjs");
const {cases} = gate.loadCases();
const plain = value => JSON.parse(JSON.stringify(value));
function fixture(item = cases[0], outcome = "sent") {
  const sandbox = {URL, Response, location: {href: "http://127.0.0.1:54321/extension/sidepanel.html", origin: "http://127.0.0.1:54321"},
    fetch: async () => {throw Error("Native fetch must never run in these fixtures");}};
  vm.createContext(sandbox); vm.runInContext(gate.initScript({}, item, outcome), sandbox);
  return sandbox;
}
function start(item, mode) {
  return {type: "start-current-task", targetTabId: 7, mode: "subtitle_only", defer: false,
    options: {content_mode: "subtitles", visual_understanding: false}, backendUrl: "http://127.0.0.1:8765", resources: [],
    learning_range: gate.expectedRange(item, mode), page: {page_url: item.page_url, title: item.title, chapters: item.chapters,
      active_video: {duration: item.duration, current_time: item.current_time, src: gate.expectedSource(item).active_video.current_src}},
    sourceIdentity: {...gate.expectedSource(item), captured_at: "2026-10-16T00:00:00.000Z", resource_fingerprint: "12345678"},
    handoffId: "ln-12345678-synthetic"};
}

test("the shared inputs drive 24 positive and 13 explicit refusal cases", () => {
  assert.match(gate.loadCases().sha256, /^[a-f0-9]{64}$/);
  const scenarios = cases.flatMap(item => gate.scenarios(item));
  assert.equal(scenarios.filter(item => item.outcome === "sent").length, 24);
  assert.equal(scenarios.filter(item => item.outcome !== "sent").length, 13);
  for (const item of cases) {
    for (const [mode, end] of [["current5", 600.25], ["current15", 1200.25], ["current30", 2100.25]]) {
      assert.deepEqual(gate.expectedRange(item, mode), {start: 300.25, end: 600});
      assert.deepEqual(gate.expectedRange({...item, duration: 2400}, mode), {start: 300.25, end});
    }
    assert.deepEqual(gate.expectedRange(item, "chapter"), item.custom_range);
    assert.deepEqual(gate.expectedRange(item, "custom"), item.custom_range);
  }
});

test("the composed locale fixture carries exact source/page/part and clones transport replies", async () => {
  for (const item of cases) {
    const env = fixture(item);
    const context = await env.chrome.runtime.sendMessage({type: "get-current-context"});
    assert.equal(context.tab.url, item.page_url); assert.equal(context.tab.id, 7);
    assert.equal(context.page.page_url, item.page_url); assert.equal(context.page.active_video.current_time, 300.25);
    assert.deepEqual(plain(context.page.chapters), item.chapters);
    assert.equal(context.page.active_video.src, gate.expectedSource(item).active_video.current_src);
    context.page.active_video.current_time = 999;
    assert.equal(env.__localeFixture.context.page.active_video.current_time, 300.25);
    assert.equal(await env.chrome.permissions.contains({origins: [new URL(item.page_url).origin + "/*"]}), true);
    assert.deepEqual(plain(await env.chrome.permissions.getAll()), {origins: [new URL(item.page_url).origin + "/*"]});
  }
});

test("denied and dismissed permissions are false without opening a native prompt", async () => {
  for (const outcome of ["permission-denied", "permission-dismissed"]) {
    const env = fixture(cases[0], outcome), request = {origins: ["https://www.bilibili.com/*"]};
    assert.equal(await env.chrome.permissions.contains(request), false);
    assert.deepEqual(plain(await env.chrome.permissions.getAll()), {origins: []});
    assert.equal(await env.chrome.permissions.request(request), false);
    assert.deepEqual(plain(env.__localeFixture.permissionRequests), [request]);
    assert.deepEqual(plain(env.__localeFixture.sent), []);
  }
});

test("fixture fetch rejects unknown local endpoints, methods, query strings and external sites", async () => {
  const env = fixture(); env.__localeFixture.connect();
  assert.equal((await (await env.fetch("http://127.0.0.1:8765/health")).json()).service, "learnnote");
  const task = await (await env.fetch("http://127.0.0.1:8765/api/tasks/locale-fixture")).json();
  assert.equal(task.task.options.content_mode, "subtitles"); assert.equal(task.task.status, "success");
  assert.equal((await (await env.fetch("http://127.0.0.1:8765/api/tasks/locale-fixture/transcript")).json()).segments.length, 12);
  for (const [url, options] of [
    ["http://127.0.0.1:8765/api/tasks/other"], ["http://127.0.0.1:8765/unknown"],
    ["http://127.0.0.1:8765/health?hidden=1"], ["http://127.0.0.1:8765/health", {method: "POST"}],
    ["http://127.0.0.1:8765/api/tasks/locale-fixture/qa"], ["http://127.0.0.1:8765/api/pairing/issue", {method: "POST"}],
    ["https://www.bilibili.com/video/BV1SYNTHETIC?p=2"], ["https://example.com/synthetic-bilibili.mp4"],
    ["http://127.0.0.1:54321/extension/sidepanel.js"]
  ]) await assert.rejects(env.fetch(url, options), /Unexpected range fixture request/);
  assert.equal(env.__localeFixture.unexpected.length, 9);
});

test("unexpected Chrome actions fail closed instead of returning permissive fixture success", async () => {
  const env = fixture();
  for (const action of [() => env.chrome.runtime.sendMessage({type: "preflight-current-page"}),
    () => env.chrome.runtime.sendMessage({type: "unknown"}), () => env.chrome.permissions.request({}),
    () => env.chrome.permissions.remove({}), () => env.chrome.tabs.create({}), () => env.chrome.tabs.update({})]) {
    await assert.rejects(action(), /Unexpected range fixture request/);
  }
  assert.equal(env.__localeFixture.unexpected.length, 6);
});

test("only real extension assets at the isolated local origin can use browser networking", () => {
  const origin = "http://127.0.0.1:54321";
  assert(gate.isAssetRequest(origin + "/extension/sidepanel.html", "GET", origin));
  assert(gate.isAssetRequest(origin + "/extension/sidepanel.js?v=0.2.15", "GET", origin));
  for (const [url, method = "GET"] of [[origin + "/api/tasks/locale-fixture"],
    [origin + "/extension/../../backend/app/main.py"], [origin + "/extension/sidepanel.html", "POST"],
    ["https://example.com/extension/sidepanel.html"], ["http://127.0.0.1:8765/health"], ["invalid URL"]]) {
    assert.equal(gate.isAssetRequest(url, method, origin), false);
  }
});

test("page, part and tab changes replace the next response and preserve the displayed snapshot", () => {
  for (const outcome of ["page-mismatch", "part-mismatch", "tab-mismatch"]) {
    const env = fixture(), old = env.__localeFixture.context;
    vm.runInContext(`(${gate.changeNextContext.toString()})(${JSON.stringify(outcome)})`, env);
    const next = env.__localeFixture.context;
    assert.notStrictEqual(next, old); assert.equal(old.tab.id, 7); assert.equal(old.page.page_url, cases[0].page_url);
    if (outcome === "page-mismatch") assert.equal(next.page.page_url, "https://example.com/different-synthetic-lesson");
    if (outcome === "part-mismatch") assert.equal(new URL(next.page.page_url).searchParams.get("p"), "3");
    if (outcome === "tab-mismatch") assert.equal(next.tab.id, 8);
  }
});

test("handoff assertions reject wrong range, source, part, tab and media/model mode", () => {
  for (const item of cases) for (const scenario of gate.scenarios(item).filter(s => s.outcome === "sent")) {
    const input = {...item, duration: scenario.duration}; gate.assertStart(start(input, scenario.mode), input, scenario.mode);
  }
  const item = cases[0];
  for (const change of [message => {message.learning_range.end = 421;}, message => {message.targetTabId = 8;},
    message => {message.sourceIdentity.tab_id = 8;}, message => {message.page.page_url = item.page_url.replace("p=2", "p=3");},
    message => {message.sourceIdentity.canonical_page_url = "https://example.com/wrong";},
    message => {message.sourceIdentity.platform_video_id = "wrong";},
    message => {message.options.content_mode = "text";}, message => {message.mode = "video";},
    message => {message.resources = [{url: "https://example.com/unexpected.mp4"}];}]) {
    const message = plain(start(item, "custom")); change(message);
    assert.throws(() => gate.assertStart(message, item, "custom"));
  }
});

test("bounded waits reject hung work and cleanup preserves the primary failure", async () => {
  assert.equal(await gate.bounded(Promise.resolve(7), "ready", 50), 7);
  await assert.rejects(gate.bounded(new Promise(() => {}), "hung response", 5), /hung response timed out/);
  const primary = Error("original assertion"), order = [];
  await assert.rejects(gate.cleanup(primary, [["context close", async () => {order.push(1); throw Error("renderer gone");}],
    ["browser close", async () => {order.push(2);}], ["server close", async () => {order.push(3);}]]), error => error === primary);
  assert.deepEqual(order, [1, 2, 3]); assert.deepEqual(primary.cleanup_errors, ["context close: renderer gone"]);
  await assert.rejects(gate.cleanup(null, [["browser close", async () => {throw Error("cannot close");}]]), /browser close: cannot close/);
  await assert.rejects(gate.cleanup(primary, [["outer close", async () => {throw Error("another close");}]]), error => error === primary);
  assert.deepEqual(primary.cleanup_errors, ["context close: renderer gone", "outer close: another close"]);
});

test("report persistence never replaces the primary browser or assertion failure", () => {
  const primary = Error("original assertion"), writerError = Error("disk full"), failedWrite = () => {throw writerError;};
  assert.throws(() => gate.writeReport("unused", {passed: false}, primary, failedWrite), error => error === primary);
  assert.equal(primary.report_write_error, "disk full");
  assert.throws(() => gate.writeReport("unused", {passed: true}, null, failedWrite), error => error === writerError);
  let saved;
  gate.writeReport("unused", {passed: true}, null, (file, contents) => {saved = {file, contents};});
  assert.match(saved.file, /report\.json$/); assert.equal(JSON.parse(saved.contents).passed, true);
});
