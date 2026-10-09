import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { File } from "node:buffer";
import { createHash } from "node:crypto";

const source = readFileSync(new URL("../material-batch.js", import.meta.url), "utf8");
const defer = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const tick = () => new Promise(resolve => setImmediate(resolve));
const file = (name, text = "Synthetic text", type = "text/plain") => new File([text], name, { type, lastModified: 1 });
function harness(newline = "\n", overrides = {}) {
  const calls = [], saved = new Map(), context = vm.createContext({ FormData, AbortController, URL });
  vm.runInContext(source.replace(/\r?\n/g, newline).replaceAll("export ", ""), context);
  const h = { calls, saved, changes: 0, previewFailures: new Set(), importFailures: new Set(), previewWaits: new Map(), importWaits: new Map(), videos: [] };
  h.api = async (path, request) => {
    const entry = { path, file: request.body.get("file"), encoding: request.body.get("encoding"), options: request.body.get("options"), signal: request.signal };
    calls.push(entry);
    const preview = path.endsWith("/preview"), waits = preview ? h.previewWaits : h.importWaits, failures = preview ? h.previewFailures : h.importFailures;
    if (waits.has(entry.file.name)) await waits.get(entry.file.name).promise;
    if (failures.has(entry.file.name)) throw new Error("Synthetic failure");
    if (preview) return { filename: entry.file.name, byte_size: entry.file.size, estimated_storage_bytes: entry.file.size * 2, encoding: entry.encoding || "utf-8", saved: false };
    const bytes = Buffer.from(await entry.file.arrayBuffer());
    const hash = createHash("sha256").update(bytes).digest("hex");
    const key = hash + (entry.options || "");
    const duplicate = saved.has(key), id = saved.get(key)?.id || `local-${saved.size}`;
    saved.set(key, { id, bytes, options: entry.options });
    return path.endsWith("/from-local") ? { task_id: id, task: { id }, deduplicated: duplicate }
      : { material: { material_id: id, deduplicated: duplicate, metadata: { encoding: entry.encoding || "utf-8" }, sha256: hash } };
  };
  h.queue = context.createMaterialBatch({ api: h.api, changed: () => h.changes++, previewVideo: async selected => { h.videos.push(selected); return { duration: null }; }, ...overrides });
  h.route = context.batchVideoRoute;
  h.kind = context.importKind;
  return h;
}
for (const newline of ["\n", "\r\n"]) {
  const h = harness(newline), selected = file("lesson.txt");
  h.queue.select([selected], "gb18030"); await h.queue.prepare();
  assert.equal(h.queue.canSubmit, true);
  assert.equal(h.calls.length, 1);
  assert.equal(h.saved.size, 0, "Preflight never commits a document");
  assert.equal(h.calls[0].file, selected, "The exact original File is used in preflight");
  await h.queue.submit({ content_mode: "subtitles" });
  assert.equal(h.calls.at(-1).file, selected, "Commit retains the exact original bytes");
  assert.equal(h.calls.at(-1).encoding, "gb18030");
  assert.equal(h.queue.items[0].status, "success");
  await h.queue.submit({ content_mode: "visual" });
  assert.equal(h.calls.length, 2, "Known success is never submitted again");
}
{
  const h = harness();
  assert.equal(h.queue.select(Array.from({ length: 21 }, (_, i) => file(`${i}.txt`))), false);
  await h.queue.prepare(); await h.queue.submit({}); assert.equal(h.calls.length, 0);
  assert.match(h.queue.message, /预检完成/);
  assert.equal(h.queue.select([{ name: "large.mp4", size: 4 * 1024 ** 3 + 1 }]), false);
  assert.match(h.queue.message, /4 GiB/);
  h.queue.select([file("bad.exe"), file("empty.txt", ""), { name: "large.txt", size: 32 * 1024 ** 2 + 1 }, file("valid.md")]);
  await h.queue.prepare(); await h.queue.submit({});
  assert.deepEqual(h.calls.map(call => call.file.name), ["valid.md", "valid.md"], "Type/size/empty checks run before any API request");
  assert.equal(h.queue.items.filter(item => item.status === "invalid").length, 3);
  const small = harness("\n", { videoLimit: () => 5 });
  small.queue.select([file("large.mp4", "123456")]); await small.queue.prepare();
  assert.equal(small.videos.length, 0, "Configured backend video size limit is honored before metadata loading");
}
{
  const h = harness(), wait = defer(); h.previewWaits.set("first.txt", wait);
  h.queue.select([file("first.txt"), file("second.txt")]); const work = h.queue.prepare();
  await tick(); assert.equal(h.calls.length, 1, "Previews are serial");
  await h.queue.submit({}); assert.equal(h.saved.size, 0, "Commit is blocked until the entire preflight finishes");
  h.queue.cancel(); assert.equal(h.calls[0].signal.aborted, true);
  wait.resolve(); await work; assert.equal(h.calls.length, 1);
  assert.equal(h.queue.items[0].status, "pending");
  h.previewWaits.clear(); await h.queue.prepare(); assert.equal(h.queue.canSubmit, true);
}
for (const failure of [false, true]) {
  const h = harness(), wait = defer(); h.previewWaits.set("old.txt", wait);
  h.queue.select([file("old.txt")]); const old = h.queue.prepare();
  h.queue.select([file("new.txt")], "big5"); await h.queue.prepare();
  const changes = h.changes;
  if (failure) wait.reject(new Error("Old preview failed")); else wait.resolve();
  await old;
  assert.equal(h.changes, changes, "Stale preflight cannot rerender the new selection");
  assert.equal(h.queue.items[0].file.name, "new.txt");
  assert.equal(h.queue.items[0].encoding, "big5");
  assert.equal(h.queue.items[0].status, "ready");
}
{
  const h = harness(); h.previewFailures.add("bad.txt");
  h.queue.select([file("good.txt", "one"), file("bad.txt", "two")]); await h.queue.prepare();
  await h.queue.submit({}); assert.equal(h.saved.size, 1);
  h.previewFailures.clear(); await h.queue.prepare(); await h.queue.submit({});
  assert.equal(h.saved.size, 2);
  assert.equal(h.calls.filter(call => call.path.endsWith("/import") && call.file.name === "good.txt").length, 1);
}
{
  const h = harness(), wait = defer();
  h.queue.select([file("one.txt", "one"), file("two.txt", "two"), file("three.txt", "three")]); await h.queue.prepare();
  h.importWaits.set("one.txt", wait);
  const run = h.queue.submit({ content_mode: "subtitles" }); await tick();
  await h.queue.submit({ content_mode: "visual" });
  assert.equal(h.calls.filter(call => call.path.endsWith("/import")).length, 1, "Repeated clicks cannot create parallel upload loops");
  assert.equal(h.queue.select([file("new.txt")]), false, "Cannot replace the batch during a commit");
  h.queue.cancel(); wait.resolve(); await run;
  assert.equal(h.saved.size, 1); assert.equal(h.queue.items[0].status, "success");
  assert.equal(h.queue.items[1].status, "ready");
  await h.queue.submit({ content_mode: "visual" });
  assert.equal(h.saved.size, 3);
  assert.equal(h.calls.filter(call => call.path.endsWith("/import") && call.file.name === "one.txt").length, 1);
}
{
  const h = harness(), wait = defer(); let current = true;
  h.queue.select([file("one.txt", "one"), file("two.txt", "two")]); await h.queue.prepare();
  h.importWaits.set("one.txt", wait); const work = h.queue.submit({}, "", () => current);
  current = false; wait.resolve(); await work;
  assert.equal(h.saved.size, 1, "A closed dialog/newer navigation blocks unsent items even before a delayed close event");
}
{
  const h = harness(), selected = { content_mode: "subtitles", visual_understanding: false, transcriber: "groq", summary_depth: "deep", local_ocr: false };
  h.queue.select([file("one.mp4", "synthetic-video-one", "video/mp4"), file("two.mp4", "synthetic-video-two", "video/mp4")]); await h.queue.prepare();
  h.importFailures.add("two.mp4"); await h.queue.submit(selected, "original route");
  selected.content_mode = "visual"; h.importFailures.clear(); await h.queue.submit(selected, "broader route");
  assert.equal(h.queue.snapshot.route, "original route");
  for (const call of h.calls) assert.equal(JSON.parse(call.options).content_mode, "subtitles", "Exact original video route is retained on retry");
  assert.equal(h.calls.filter(call => call.file.name === "one.mp4").length, 1);
  assert.match(h.route({ content_mode: "subtitles", transcriber: "groq" }), /不调用转写或总结模型/);
  for (const transcriber of ["groq", "groq-asr", "openai", "openai-compatible", "openai-compatible-asr"]) {
    const route = h.route({ content_mode: "visual", visual_understanding: true, transcriber,
      llm_base_url: "https://text-provider.invalid/v1", llm_model: "fixture" });
    const [audioRoute, textRoute] = route.split("。");
    assert.match(audioRoute, transcriber.startsWith("groq") ? /所选 Groq 转写服务配置的地址/ : /所选 OpenAI 兼容 转写服务配置的地址/);
    assert.match(audioRoute, /未确认实际转写地址/);
    assert.doesNotMatch(audioRoute, /text-provider\.invalid/, "A distinct text-model host must not be presented as the effective ASR destination");
    assert.match(textRoute, /字幕与选定画面.*text-provider\.invalid.*fixture/);
  }
}
{
  const h = harness();
  h.queue.select([file("same.txt", "same"), file("copy.txt", "same"), file("same.txt", "diff")]);
  await h.queue.prepare(); await h.queue.submit({});
  assert.equal(h.calls.filter(call => call.path.endsWith("/import")).length, 3, "Metadata never silently skips a selected file");
  assert.equal(h.saved.size, 2, "Only actual content identity deduplicates");
  assert.equal(h.queue.items[1].result.material.deduplicated, true);
  assert.match(h.queue.items[1].detail, /内容哈希相同/);
}
// Metadata probes are bounded and always release the blob URL, including
// unsupported browser codecs, non-finite duration, timeout and cancellation.
for (const outcome of ["duration", "unknown", "error", "timeout", "cancel"]) {
  let timer, cleanup = 0, revoked = 0, video;
  const context = vm.createContext({
    AbortController,
    document: { createElement() { return video = { duration: outcome === "unknown" ? Infinity : 12.5, load() { cleanup++; }, removeAttribute() {} }; } },
    URL: { createObjectURL() { return "blob:synthetic"; }, revokeObjectURL(url) { assert.equal(url, "blob:synthetic"); revoked++; } },
    setTimeout(fn, delay) { assert.equal(delay, 10000); timer = fn; return 1; }, clearTimeout() {},
  });
  vm.runInContext(source.replaceAll("export ", ""), context);
  const signal = new AbortController(), work = context.previewVideoFile(file("video.mp4"), { signal: signal.signal });
  if (outcome === "timeout") timer(); else if (outcome === "cancel") signal.abort(); else if (outcome === "error") video.onerror(); else video.onloadedmetadata();
  assert.equal((await work).duration, outcome === "duration" ? 12.5 : null);
  assert.equal(revoked, 1); assert.equal(cleanup, 1); assert.equal(video.onerror, null); assert.equal(video.onloadedmetadata, null);
}
{
  let commits = 0;
  const h = harness("\n", { api: async path => {
    if (path.endsWith("/preview")) return { estimated_storage_bytes: 16 };
    commits++;
    return { material: { material_id: "existing", deduplicated: true, metadata: { encoding: "big5" } } };
  } });
  h.queue.select([file("existing.txt")], "gb18030"); await h.queue.prepare(); await h.queue.submit({});
  assert.equal(h.queue.items[0].status, "success", "A known existing result is not mislabeled retryable on encoding mismatch");
  assert.match(h.queue.items[0].detail, /big5.*没有覆盖/);
  await h.queue.submit({}); assert.equal(commits, 1);
}
console.log("Bounded batch import preserves original bytes, serial preflight/uploads, hash-backed reuse, retries, cancellation, option snapshots and LF/CRLF races");
