import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const hookCode = await readFile(new URL("../page_hook.js", import.meta.url), "utf8");
const requestHeaders = Object.freeze({
  aUtHoRiZaTiOn: "Bearer SENTINEL",
  Accept: "application/json",
  Referer: "https://lesson.invalid/course"
});
const requestSnapshot = JSON.stringify(requestHeaders);

async function capture(transport, requestUrl, responseUrl, candidateUrl) {
  const messages = [];
  const data = { videoUrl: candidateUrl, mimeType: "video/mp4" };
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
    open() {}
    setRequestHeader() {}
    addEventListener(name, callback) { this[name] = callback; }
    getResponseHeader(name) { return name === "content-type" ? "application/json" : ""; }
    send() { this.loadend(); }
  }
  const response = new FakeResponse();
  const context = vm.createContext({
    URL, Response: FakeResponse, XMLHttpRequest: FakeXHR,
    location: { href: "https://lesson.invalid/course" },
    document: { addEventListener() {} }, navigator: {},
    fetch: async () => response,
    caches: { match: async () => response },
    setTimeout() {}, clearTimeout() {},
    addEventListener() {}, postMessage: message => messages.push(message)
  });
  context.window = context;
  vm.runInContext(hookCode, context);
  if (transport === "xhr") {
    const xhr = new context.XMLHttpRequest();
    xhr.open("GET", requestUrl);
    for (const [name, value] of Object.entries(requestHeaders)) xhr.setRequestHeader(name, value);
    const originalHeaders = JSON.stringify(xhr.__learnNoteRequestHeaders);
    xhr.send();
    assert.equal(JSON.stringify(xhr.__learnNoteRequestHeaders), originalHeaders);
  } else {
    const request = Object.freeze({ url: requestUrl, headers: requestHeaders });
    const result = transport === "fetch" ? await context.fetch(request) : await context.caches.match(request);
    assert.equal(result, response);
    assert.equal(await result.json(), data);
    assert.equal(request.url, requestUrl);
    assert.equal(request.headers, requestHeaders);
  }
  assert.equal(JSON.stringify(requestHeaders), requestSnapshot);
  const resources = messages.flatMap(message => message.resources || []);
  const responseResource = resources.find(item => item.url === responseUrl);
  const candidate = resources.find(item => item.url === candidateUrl);
  assert.ok(responseResource, `Missing ${transport} response resource for ${responseUrl}`);
  assert.ok(candidate, `Missing ${transport} body candidate for ${candidateUrl}`);
  return [responseResource, candidate];
}

const cases = [
  ["https://media.invalid/api/play.mp4", "https://media.invalid/api/play.mp4", "https://media.invalid/video.mp4", true, true],
  ["https://MEDIA.invalid:443/api/play.mp4", "https://media.invalid/api/play.mp4", "https://media.invalid/video.mp4", true, true],
  ["http://media.invalid:80/api/play.mp4", "http://media.invalid/api/play.mp4", "http://media.invalid/video.mp4", true, true],
  ["https://media.invalid:8443/api/play.mp4", "https://media.invalid:8443/api/play.mp4", "https://media.invalid:8443/video.mp4", true, true],
  ["https://media.invalid/api/play.mp4", "https://cdn.invalid/api/play.mp4", "https://cdn.invalid/video.mp4", false, false],
  ["https://media.invalid/api/play.mp4", "https://cdn.invalid/api/play.mp4", "https://media.invalid/video.mp4", false, false],
  ["https://media.invalid/api/play.mp4", "http://media.invalid/api/play.mp4", "http://media.invalid/video.mp4", false, false],
  ["https://media.invalid/api/play.mp4", "https://media.invalid:8443/api/play.mp4", "https://media.invalid:8443/video.mp4", false, false],
  ["https://media.invalid/api/play.mp4", "https://media.invalid/api/play.mp4", "https://cdn.invalid/video.mp4", true, false],
  ["https://media.invalid/api/play.mp4", "https://media.invalid/api/play.mp4", "https://sub.media.invalid/video.mp4", true, false],
  ["https://media.invalid/api/play.mp4", "https://media.invalid/api/play.mp4", "http://media.invalid/video.mp4", true, false],
  ["https://media.invalid/api/play.mp4", "https://media.invalid/api/play.mp4", "https://media.invalid:8443/video.mp4", true, false],
  ["https://media.invalid/api/play.mp4", "https://media.invalid/api/play.mp4", "https://fixture@media.invalid/video.mp4", true, false],
  ["", "https://media.invalid/api/play.mp4", "https://media.invalid/video.mp4", false, false],
  ["/api/play.mp4", "https://media.invalid/api/play.mp4", "https://media.invalid/video.mp4", false, false],
  ["https:///media.invalid/api/play.mp4", "https://media.invalid/api/play.mp4", "https://media.invalid/video.mp4", false, false],
  ["https://media.invalid:bad/api/play.mp4", "https://media.invalid/api/play.mp4", "https://media.invalid/video.mp4", false, false],
  ["https://fixture@media.invalid/api/play.mp4", "https://media.invalid/api/play.mp4", "https://media.invalid/video.mp4", false, false]
];
for (const transport of ["fetch", "xhr", "cache"]) {
  for (const [requestUrl, responseUrl, candidateUrl, keepResponseAuth, keepCandidateAuth] of cases) {
    const resources = await capture(transport, requestUrl, responseUrl, candidateUrl);
    for (const [index, keepAuth] of [keepResponseAuth, keepCandidateAuth].entries()) {
      const headers = resources[index].request_headers;
      assert.equal(headers.Authorization, keepAuth ? "Bearer SENTINEL" : undefined,
        `${transport}: ${requestUrl} -> ${resources[index].url}`);
      assert.equal(headers.Accept, requestHeaders.Accept);
      assert.equal(headers.Referer, requestHeaders.Referer);
    }
  }
}
console.log("Fetch, XHR and cache candidates preserve Authorization only across matching original origins");
