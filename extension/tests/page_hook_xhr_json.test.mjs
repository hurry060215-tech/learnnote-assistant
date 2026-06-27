import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

class FakeXHR {
  constructor() {
    this.listeners = new Map();
    this.responseType = "json";
    this.response = {
      data: {
        playUrl: "https%3A%2F%2Fcdn.example.com%2Fcourse%2Flesson.m3u8%3Ftoken%3Dxhr",
        mediaType: "application/vnd.apple.mpegurl"
      }
    };
    this.responseURL = "https://course.example.com/api/play-json";
    this.status = 200;
  }

  open(method, url) {
    this.method = method;
    this.url = url;
  }

  send() {
    for (const listener of this.listeners.get("loadend") || []) {
      listener.call(this);
    }
  }

  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(listener);
  }

  setRequestHeader(name, value) {
    this.headers ||= {};
    this.headers[name] = value;
  }

  getResponseHeader(name) {
    if (String(name).toLowerCase() === "content-type") return "application/json";
    if (String(name).toLowerCase() === "content-length") return "8192";
    return "";
  }
}

const context = {
  window: null,
  location: { href: "https://course.example.com/player" },
  document: { addEventListener() {} },
  navigator: {},
  XMLHttpRequest: FakeXHR,
  URL,
  atob: value => Buffer.from(value, "base64").toString("binary"),
  setTimeout,
  clearTimeout,
  console
};
context.window = context;
context.window.addEventListener = () => {};
context.window.postMessage = message => messages.push(message);
context.window.HTMLMediaElement = function HTMLMediaElement() {};
context.window.HTMLMediaElement.prototype = {};

vm.createContext(context);
const hookCode = await readFile(new URL("../page_hook.js", import.meta.url), "utf8");
vm.runInContext(hookCode, context);

const xhr = new context.XMLHttpRequest();
xhr.open("GET", "https://course.example.com/api/play-json");
xhr.setRequestHeader("Accept", "application/json");
xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
xhr.setRequestHeader("Cookie", "secret=bad");
xhr.send();

const resources = messages.flatMap(message => message.resources || []);
const hls = resources.find(resource => resource.url === "https://cdn.example.com/course/lesson.m3u8?token=xhr");

assert.ok(hls, "expected XHR responseType=json body to expose the encoded HLS URL");
assert.equal(hls.kind, "hls");
assert.equal(hls.source, "pageHookBody");
assert.match(hls.label, /xhr json/);
assert.equal(hls.request_type, "xmlhttprequest");
assert.equal(hls.method, "GET");
assert.equal(hls.status_code, 200);
assert.equal(hls.content_length, 8192);
assert.equal(hls.initiator, "https://course.example.com/api/play-json");
assert.equal(hls.headers["content-type"], "application/json");
assert.equal(hls.headers["content-length"], "8192");
assert.equal(hls.request_headers.Accept, "application/json");
assert.equal(hls.request_headers["X-Requested-With"], "XMLHttpRequest");
assert.equal(hls.request_headers.Cookie, undefined);
