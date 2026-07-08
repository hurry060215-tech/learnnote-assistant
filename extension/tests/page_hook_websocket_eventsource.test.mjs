import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

class FakeRealtimeSource {
  constructor(url) {
    this.url = url;
    this.listeners = {};
  }

  addEventListener(type, listener) {
    this.listeners[type] = this.listeners[type] || [];
    this.listeners[type].push(listener);
  }

  emit(type, event) {
    for (const listener of this.listeners[type] || []) {
      listener(event);
    }
  }
}

class FakeWebSocket extends FakeRealtimeSource {}
class FakeEventSource extends FakeRealtimeSource {}

const context = {
  window: null,
  location: { href: "https://course.example.com/player/index.html" },
  document: { addEventListener() {} },
  navigator: {},
  WebSocket: FakeWebSocket,
  EventSource: FakeEventSource,
  Response: undefined,
  Blob: undefined,
  ArrayBuffer,
  MediaSource: undefined,
  SourceBuffer: undefined,
  URL,
  URLSearchParams,
  atob: value => Buffer.from(value, "base64").toString("binary"),
  setTimeout() {
    return 0;
  },
  clearTimeout() {},
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

const socket = new context.WebSocket("wss://course.example.com/player/socket");
socket.emit("message", {
  data: JSON.stringify({
    data: {
      hlsUrl: "https://cdn.example.com/ws/master.m3u8?token=socket",
      play_url: "/ws/play?id=42"
    }
  })
});

const eventSource = new context.EventSource("/player/events");
eventSource.emit("message", {
  data: JSON.stringify({
    sources: [{ file: "https://cdn.example.com/sse/lesson.mp4?token=events" }]
  })
});

const countBeforeBinary = messages.flatMap(message => message.resources || []).length;
socket.emit("message", { data: new Uint8Array([0, 1, 2, 3]).buffer });
assert.equal(messages.flatMap(message => message.resources || []).length, countBeforeBinary);

const resources = messages.flatMap(message => message.resources || []);
const byUrl = new Map(resources.map(resource => [resource.url, resource]));

assert.equal(byUrl.get("https://cdn.example.com/ws/master.m3u8?token=socket")?.source, "pageHookWebSocket");
assert.equal(byUrl.get("https://cdn.example.com/ws/master.m3u8?token=socket")?.kind, "hls");
assert.match(byUrl.get("https://cdn.example.com/ws/master.m3u8?token=socket")?.label || "", /websocket message/);
assert.equal(byUrl.get("https://course.example.com/ws/play?id=42")?.source, "pageHookWebSocket");
assert.equal(byUrl.get("https://course.example.com/ws/play?id=42")?.kind, "video");
assert.equal(byUrl.get("https://cdn.example.com/sse/lesson.mp4?token=events")?.source, "pageHookEventSource");
assert.equal(byUrl.get("https://cdn.example.com/sse/lesson.mp4?token=events")?.kind, "video");
