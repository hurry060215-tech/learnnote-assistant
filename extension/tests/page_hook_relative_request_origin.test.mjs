import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const code = await readFile(new URL("../page_hook.js", import.meta.url), "utf8");
const pageUrl = "https://lesson.invalid/course";
const originalToken = "Bearer SENTINEL_ORIGINAL";

function fixture({ base, page = pageUrl, responseUrl, candidateUrl }) {
  const messages = [];
  const calls = [];
  const data = { videoUrl: candidateUrl, mimeType: "video/mp4" };
  let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  class FakeResponse {
    url = responseUrl;
    status = 200;
    headers = { get: name => name === "content-type" ? "application/json" : "" };
    clone() { throw new Error("Offline fixture has no clone"); }
    async json() { return data; }
  }
  class FakeXHR {
    responseURL = responseUrl;
    responseType = "json";
    response = data;
    status = 200;
    open(method, url) { calls.push({ method, input: url }); }
    setRequestHeader() {}
    addEventListener(name, callback) { this[name] = callback; }
    getResponseHeader(name) { return name === "content-type" ? "application/json" : ""; }
    send() {}
  }
  class FakeCache {
    match(input) { calls.push({ input }); return pending; }
    async matchAll(input) { calls.push({ input }); return [await pending]; }
  }
  const context = vm.createContext({
    URL, Response: FakeResponse, XMLHttpRequest: FakeXHR, Cache: FakeCache,
    location: { href: page }, document: { baseURI: base, addEventListener() {} }, navigator: {},
    fetch: (input, init) => { calls.push({ input, init }); return pending; },
    caches: { match: input => { calls.push({ input }); return pending; } },
    setTimeout() {}, clearTimeout() {}, addEventListener() {},
    postMessage: message => messages.push(message)
  });
  context.window = context;
  vm.runInContext(code, context);
  const response = new FakeResponse();
  return { context, messages, calls, response, finish: () => finish(response), resources: () => messages.flatMap(item => item.resources || []) };
}

async function relativeRequest(transport, { input = "/api/play.mp4", base, page = pageUrl, origin, keep, mutateBase, navigate, mutateHeaders = false }) {
  const responseUrl = `${origin}/api/play.mp4`;
  const candidateUrl = `${origin}/video.mp4`;
  const env = fixture({ base, page, responseUrl, candidateUrl });
  const headers = { Authorization: originalToken, Accept: "application/json" };
  const init = Object.freeze({ headers });
  let result;
  let xhr;
  if (transport === "fetch") {
    result = env.context.fetch(input, init);
    assert.equal(env.calls.length, 1, "Fetch must dispatch before awaiting body inspection");
    assert.equal(env.calls[0].input, input);
    assert.equal(env.calls[0].init, init);
  } else {
    xhr = new env.context.XMLHttpRequest();
    xhr.open("GET", input);
    for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);
    assert.equal(env.calls[0].input, input, "XHR.open receives the original relative input");
  }
  const expectedHeaders = { ...headers };
  if (mutateHeaders) headers.Authorization = expectedHeaders.Authorization = "Bearer SENTINEL_LATER";
  if (mutateBase !== undefined) env.context.document.baseURI = mutateBase;
  if (navigate) env.context.location.href = navigate;
  if (xhr) {
    const savedHeaders = JSON.stringify(xhr.__learnNoteRequestHeaders);
    xhr.send();
    xhr.loadend();
    assert.equal(JSON.stringify(xhr.__learnNoteRequestHeaders), savedHeaders);
  } else {
    env.finish();
    assert.equal(await result, env.response);
  }
  if (navigate) {
    assert.equal(env.resources().length, 0, "Old-page evidence must stay out of the new page");
    env.context.location.href = page;
    if (xhr) xhr.loadend();
  }
  if (!xhr) await env.response.json();
  assert.deepEqual(headers, expectedHeaders, "Inspection must not mutate caller headers");
  assert.equal(init.headers, headers);
  if (!page) {
    assert.equal(env.resources().length, 0, "Unknown page and request base must not emit borrowed evidence");
    return;
  }
  const candidate = env.resources().find(item => item.url === candidateUrl);
  assert.ok(candidate, `${transport}: missing candidate for ${input} with base ${base}`);
  assert.equal(candidate.request_headers.Authorization, keep ? originalToken : undefined,
    `${transport}: ${input} with original base ${base} must not borrow ${mutateBase || origin}`);
  assert.equal(candidate.request_headers.Accept, "application/json");
}

const cases = [
  { base: "https://lesson.invalid/", origin: "https://lesson.invalid", keep: true },
  { input: "", base: "https://lesson.invalid/api/play.mp4", origin: "https://lesson.invalid", keep: true },
  { base: undefined, origin: "https://lesson.invalid", keep: true },
  { base: "", origin: "https://lesson.invalid", keep: true },
  { input: "api/play.mp4", base: "https://media.invalid/assets/", origin: "https://media.invalid", keep: true },
  { base: "https://MEDIA.invalid:443/", origin: "https://media.invalid", keep: true },
  { base: "https://media.invalid/", origin: "https://lesson.invalid", keep: false },
  { base: "http://media.invalid:8080/", origin: "http://media.invalid:8080", keep: true },
  { input: "//media.invalid/api/play.mp4", base: "https://lesson.invalid/", origin: "https://media.invalid", keep: true },
  { base: "not a URL", origin: "https://lesson.invalid", keep: false },
  { base: "https:///lesson.invalid/", origin: "https://lesson.invalid", keep: false },
  { base: "https://fixture@lesson.invalid/", origin: "https://lesson.invalid", keep: false },
  { base: "https://lesson.invalid:bad/", origin: "https://lesson.invalid", keep: false },
  { base: undefined, page: "", origin: "https://lesson.invalid", keep: false },
  { base: "https://lesson.invalid/", origin: "https://lesson.invalid", keep: true, mutateBase: "https://later.invalid/" },
  { base: "https://lesson.invalid/", origin: "https://later.invalid", keep: false, mutateBase: "https://later.invalid/" },
  { base: "https://lesson.invalid/", origin: "https://later.invalid", keep: false, mutateBase: "https://later.invalid/", navigate: "https://later.invalid/course" },
  { base: "https://lesson.invalid/", origin: "https://lesson.invalid", keep: true, mutateBase: "https://later.invalid/", navigate: "https://later.invalid/course" },
  { base: "https://lesson.invalid/", origin: "https://lesson.invalid", keep: true, mutateHeaders: true }
];
for (const transport of ["fetch", "xhr"]) {
  for (const item of cases) await relativeRequest(transport, item);
}

for (const origin of ["https://lesson.invalid", "https://later.invalid"]) {
  const target = `${origin}/api/play.mp4`;
  const env = fixture({ base: "https://lesson.invalid/", responseUrl: target, candidateUrl: `${origin}/video.mp4` });
  const xhr = new env.context.XMLHttpRequest();
  xhr.open("GET", "/api/play.mp4");
  xhr.setRequestHeader("Authorization", originalToken);
  xhr.setRequestHeader("Accept", "application/json");
  const originalHeaders = xhr.__learnNoteRequestHeaders;
  xhr.send();
  xhr.__learnNoteUrl = "https://later.invalid/api/play.mp4";
  originalHeaders.Authorization = "Bearer SENTINEL_LATER";
  env.context.document.baseURI = "https://later.invalid/";
  xhr.loadend();
  const candidate = env.resources().find(item => item.url === `${origin}/video.mp4`);
  assert.equal(candidate.request_headers.Authorization, origin === "https://lesson.invalid" ? originalToken : undefined);
  assert.equal(xhr.__learnNoteRequestHeaders, originalHeaders);
  assert.deepEqual({ ...originalHeaders }, { Authorization: "Bearer SENTINEL_LATER", Accept: "application/json" });
  assert.equal(xhr.__learnNoteUrl, "https://later.invalid/api/play.mp4");
  assert.equal(env.calls[0].input, "/api/play.mp4");
}

for (const transport of ["cache-storage", "cache-match", "cache-matchAll"]) {
  const target = "https://original.invalid/api/play.mp4";
  const env = fixture({ base: "https://original.invalid/", responseUrl: "", candidateUrl: target });
  const cache = new env.context.Cache();
  const pending = transport === "cache-storage" ? env.context.caches.match("/api/play.mp4")
    : cache[transport === "cache-match" ? "match" : "matchAll"]("/api/play.mp4");
  assert.equal(env.calls[0].input, "/api/play.mp4");
  env.context.document.baseURI = "https://later.invalid/";
  env.context.location.href = "https://later.invalid/course";
  env.finish();
  await pending;
  assert.equal(env.resources().length, 0);
  env.context.location.href = pageUrl;
  await env.response.json();
  const candidate = env.resources().find(item => item.url === target);
  assert.ok(candidate);
  assert.equal(candidate.initiator, target, `${transport} must use the URL captured before await`);
}

for (const transport of ["fetch", "cache-storage", "cache-match", "cache-matchAll"]) {
  const target = "https://absolute.invalid/api/play.mp4";
  const env = fixture({ base: "invalid base", responseUrl: target, candidateUrl: "https://absolute.invalid/video.mp4" });
  const headers = { Authorization: originalToken, Accept: "application/json" };
  const request = Object.freeze({ url: target, headers });
  const cache = new env.context.Cache();
  const pending = transport === "fetch" ? env.context.fetch(request)
    : transport === "cache-storage" ? env.context.caches.match(request)
      : cache[transport === "cache-match" ? "match" : "matchAll"](request);
  assert.equal(env.calls[0].input, request);
  headers.Authorization = "Bearer SENTINEL_LATER";
  env.context.document.baseURI = "https://later.invalid/";
  env.finish();
  await pending;
  await env.response.json();
  const candidate = env.resources().find(item => item.url === "https://absolute.invalid/video.mp4");
  assert.equal(candidate.request_headers.Authorization, originalToken);
  assert.equal(request.url, target);
  assert.equal(request.headers, headers);
  assert.deepEqual(headers, { Authorization: "Bearer SENTINEL_LATER", Accept: "application/json" });
}
console.log("Relative fetch/XHR and cache provenance uses the dispatch base and original headers across delayed changes");
