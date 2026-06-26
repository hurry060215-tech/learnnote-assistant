import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

class FakeHeaders {
  get(name) {
    if (String(name).toLowerCase() === "content-type") return "text/plain; charset=utf-8";
    return "";
  }
}

class FakeResponse {
  constructor(text) {
    this.value = text;
    this.url = "https://course.example.com/api/play-text";
    this.headers = new FakeHeaders();
    this.body = null;
  }

  clone() {
    throw new Error("clone unavailable");
  }

  async text() {
    return this.value;
  }
}

const responseText = JSON.stringify({
  playInfo: {
    videoUrl: "https%3A%2F%2Fcdn.example.com%2Ftext%2Flesson.mp4%3Ftoken%3Dfetch-text",
    format: "video/mp4"
  }
});

const context = {
  window: null,
  location: { href: "https://course.example.com/player" },
  document: { addEventListener() {} },
  navigator: {},
  Response: FakeResponse,
  Blob,
  ArrayBuffer,
  URL,
  atob: value => Buffer.from(value, "base64").toString("binary"),
  fetch: async () => new FakeResponse(responseText),
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

const response = await context.fetch("https://course.example.com/api/play-text");
const text = await response.text();

assert.equal(text, responseText);

const resources = messages.flatMap(message => message.resources || []);
const video = resources.find(resource => resource.url === "https://cdn.example.com/text/lesson.mp4?token=fetch-text");

assert.ok(video, "expected Response.text() body to expose the encoded video URL");
assert.equal(video.kind, "video");
assert.equal(video.source, "pageHookBody");
assert.match(video.label, /fetch text/);
