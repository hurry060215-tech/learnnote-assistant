import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { File } from "node:buffer";

const source = readFileSync(new URL("../material-batch.js", import.meta.url), "utf8");
const apiSource = readFileSync(new URL("../desk-api.js", import.meta.url), "utf8");
const file = (name, content = name) => new File([content], name, { type: "video/x-matroska" });
const defer = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const tick = () => new Promise(resolve => setImmediate(resolve));
const httpError = (status, code) => Object.assign(new Error(code), { status, code });
function harness({ nativeDuration = null, newline = "\n" } = {}) {
  const context = vm.createContext({ FormData, AbortController, URL });
  vm.runInContext(source.replace(/\r?\n/g, newline).replaceAll("export ", ""), context);
  const h = { calls: [], stages: new Map(), tasks: new Map(), changes: 0, wait: null, nextError: null, loseResponse: false, malformedResponse: false, previews: 0 };
  h.queue = context.createMaterialBatch({
    previewVideo: async () => ({ duration: nativeDuration }), changed: () => h.changes++,
    api: async (path, request) => {
      const selected = request.body.get("file"), token = request.body.get("staging_token");
      const options = request.body.get("options");
      h.calls.push({ path, file: selected, token, options, signal: request.signal });
      if (path.endsWith("/preflight-local")) {
        h.previews++;
        assert.equal(options, null, "Metadata fallback never sends processing settings or invokes models");
        if (h.wait) await h.wait.promise;
        if (h.nextError) { const error = h.nextError; h.nextError = null; throw error; }
        const staging_token = String(h.previews).padStart(32, "0");
        h.stages.set(staging_token, selected);
        return { duration: 92.5, staging_token, source_fingerprint: "a".repeat(64), integrity: { status: "ready" } };
      }
      if (h.nextError) { const error = h.nextError; h.nextError = null; throw error; }
      if (token && !h.stages.has(token)) throw httpError(404, "staging_token_not_found");
      const original = token ? h.stages.get(token) : selected;
      if (token) { assert.equal(selected, null, "Token submission must not upload bytes again"); h.stages.delete(token); }
      const id = `task-${h.tasks.size + 1}`;
      h.tasks.set(id, { original, options });
      if (h.loseResponse) { h.loseResponse = false; throw new TypeError("Lost network response"); }
      return h.malformedResponse ? {} : { task_id: id };
    },
  });
  return h;
}
for (const newline of ["\n", "\r\n"]) {
  const h = harness({ newline }), selected = file("lesson.mkv");
  h.queue.select([selected]); await h.queue.prepare();
  assert.equal(h.queue.items[0].preview.duration, 92.5);
  assert.equal(h.calls[0].file, selected, "Fallback preserves the original File object and bytes");
  assert.equal(h.tasks.size, 0);
  await h.queue.submit({ content_mode: "subtitles" });
  assert.equal(h.calls.length, 2); assert.equal(h.calls[1].file, null);
  assert.equal(h.tasks.values().next().value.original, selected);
  await h.queue.submit({ content_mode: "visual" }); assert.equal(h.calls.length, 2);
}
{
  const h = harness({ nativeDuration: 13 });
  h.queue.select([file("native.mp4")]); await h.queue.prepare();
  assert.equal(h.calls.length, 0, "Known browser duration avoids any preflight upload");
  await h.queue.submit({}); assert(h.calls[0].file); assert.equal(h.calls[0].token, null);
}
for (const nativeDuration of [NaN, Infinity, 0, -1]) {
  const h = harness({ nativeDuration }); h.queue.select([file("unreadable.mkv")]); await h.queue.prepare();
  assert.equal(h.previews, 1); assert.equal(h.queue.items[0].preview.duration, 92.5);
}
{
  const native = defer(), calls = [];
  const context = vm.createContext({ FormData, AbortController });
  vm.runInContext(source.replaceAll("export ", ""), context);
  const queue = context.createMaterialBatch({ previewVideo: () => native.promise, api: async path => calls.push(path) });
  queue.select([file("cancel-native.mkv")]); const work = queue.prepare(); queue.cancel();
  native.resolve({ duration: null }); await work;
  assert.equal(calls.length, 0, "Cancellation during browser metadata must not start the fallback upload");
}
for (const result of [{ duration: null, staging_token: "a".repeat(32) }, { duration: 5 }, { duration: 5, staging_token: "invalid-token" }]) {
  const context = vm.createContext({ FormData, AbortController });
  vm.runInContext(source.replaceAll("export ", ""), context);
  const queue = context.createMaterialBatch({ previewVideo: async () => ({ duration: null }), api: async () => result });
  queue.select([file("bad-response.mkv")]); await queue.prepare();
  assert.equal(queue.canSubmit, false); assert.equal(queue.items[0].status, "failed");
  assert.match(queue.items[0].detail, /有效的时长与暂存结果/);
}
{
  const h = harness(), selected = file("expired.mkv"), options = { content_mode: "subtitles" };
  h.queue.select([selected, file("neighbour.mkv")]); await h.queue.prepare();
  h.stages.delete(h.queue.items[0].preview.staging_token);
  await h.queue.submit(options, "original route");
  assert.equal(h.tasks.size, 1); assert.equal(h.queue.items[0].preview, null);
  assert.match(h.queue.items[0].detail, /重新预检未完成项/);
  assert.equal(h.queue.items[1].status, "success");
  options.content_mode = "visual";
  await h.queue.prepare(); await h.queue.submit(options, "changed route");
  assert.equal(h.tasks.size, 2); assert.equal(h.previews, 3, "Only the expired file is uploaded again");
  assert.equal(h.calls.filter(call => call.file === selected).length, 2);
  assert.equal(h.queue.snapshot.route, "original route");
  for (const call of h.calls.filter(call => call.options)) assert.equal(JSON.parse(call.options).content_mode, "subtitles");
}
for (const lost of ["network", "malformed", "server"]) {
  const h = harness(); h.queue.select([file("lost-response.mkv"), file("neighbour.mkv")]); await h.queue.prepare();
  if (lost === "network") h.loseResponse = true;
  if (lost === "malformed") h.malformedResponse = true;
  if (lost === "server") h.nextError = httpError(500, "internal_error");
  await h.queue.submit({ content_mode: "subtitles" });
  h.malformedResponse = false;
  // A 5xx may happen after creation too. Model its consumed token explicitly.
  if (lost === "server") h.stages.delete(h.queue.items[0].preview.staging_token);
  const tasks = h.tasks.size;
  await h.queue.submit({ content_mode: "visual" });
  assert.equal(h.queue.items[0].status, "unconfirmed");
  assert.match(h.queue.items[0].detail, /资料库.*失败或取消.*不会自动重新上传/);
  await h.queue.prepare(); await h.queue.submit({});
  assert.equal(h.tasks.size, tasks, "A consumed uncertain token must never cause a second task, even after failure/cancellation");
  assert.equal(h.previews, 2, "Unconfirmed items cannot be re-preflighted automatically");
  assert.equal(h.queue.canSubmit, false);
}
{
  const h = harness(); h.queue.select([file("safe-retry.mkv")]); await h.queue.prepare();
  h.nextError = new TypeError("Request never arrived"); await h.queue.submit({ content_mode: "subtitles" });
  await h.queue.submit({ content_mode: "visual" });
  assert.equal(h.tasks.size, 1); assert.equal(h.previews, 1);
  assert.equal(h.calls[1].token, h.calls[2].token, "Retry an uncertain request using the same still-valid token");
  assert.equal(JSON.parse(h.calls[2].options).content_mode, "subtitles");
}
for (const action of ["cancel", "replace"]) {
  const h = harness(); h.wait = defer();
  h.queue.select([file("old.mkv"), file("unsent.mkv")]); const work = h.queue.prepare(); await tick();
  assert.equal(h.calls.length, 1, "Fallback uploads remain serial");
  const oldWait = h.wait; h.wait = null;
  if (action === "cancel") h.queue.cancel();
  else { h.queue.select([file("new.mkv")]); await h.queue.prepare(); }
  assert.equal(h.calls[0].signal.aborted, true);
  const changes = h.changes;
  oldWait.resolve(); await work;
  assert.equal(h.changes, changes, "A late local preflight cannot alter the current selection or cancellation state");
  assert.equal(h.tasks.size, 0);
  assert.equal(h.calls.some(call => call.file?.name === "unsent.mkv"), false);
}
{
  const h = harness(); h.nextError = httpError(400, "invalid_local_video");
  h.queue.select([file("invalid.mkv")]); await h.queue.prepare(); await h.queue.submit({});
  assert.equal(h.tasks.size, 0); assert.equal(h.queue.canSubmit, false);
  assert.equal(h.queue.items[0].preview, null); assert.equal(h.queue.items[0].status, "failed");
}
for (const [body, status, code, message] of [
  [{ detail: { code: "staging_token_not_found", message: "Missing staging" } }, 404, "staging_token_not_found", /Missing staging/],
  [{ detail: [{ loc: ["body", "options"], msg: "invalid" }] }, 422, "", /body.options: invalid/],
  ["Gateway failed", 502, "", /502/],
]) {
  const context = vm.createContext({ FormData, fetch: async () => ({ ok: false, status, text: async () => JSON.stringify(body) }) });
  vm.runInContext(apiSource.replaceAll("export ", ""), context);
  await assert.rejects(context.api("/fixture"), error => error.status === status && error.code === code && message.test(error.message));
}
console.log("Local video fallback preserves bytes, token-only submission, frozen retries, expiry recovery, conservative uncertain outcomes and cancelled/stale preflights");
