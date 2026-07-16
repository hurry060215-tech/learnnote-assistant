import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];
const listeners = new Map();
const location = { href: "https://course.example.com/lesson-1" };
const context = {
  window: null,
  location,
  history: {
    pushState(_state, _title, url) {
      location.href = new URL(url, location.href).href;
    },
    replaceState(_state, _title, url) {
      location.href = new URL(url, location.href).href;
    }
  },
  document: { addEventListener() {} },
  navigator: {},
  Response: class Response {},
  Blob,
  ArrayBuffer,
  URL,
  URLSearchParams,
  atob: value => Buffer.from(value, "base64").toString("binary"),
  __playInfo: { videoUrl: "https://cdn.example.com/lesson-1.mp4" },
  fetch: undefined,
  setTimeout() { return 0; },
  clearTimeout() {},
  console
};
context.window = context;
context.window.addEventListener = (type, listener) => {
  const values = listeners.get(type) || [];
  values.push(listener);
  listeners.set(type, values);
  if (type === "message") context.pageMessageListener = listener;
};
context.window.postMessage = message => messages.push(message);
context.window.HTMLMediaElement = function HTMLMediaElement() {};
context.window.HTMLMediaElement.prototype = {};

vm.createContext(context);
const hookCode = await readFile(new URL("../page_hook.js", import.meta.url), "utf8");
vm.runInContext(hookCode, context);

assert.equal(messages.some(message => message.resources?.some(item => item.url === "https://cdn.example.com/lesson-1.mp4")), true);
const oldIdentity = messages.find(message => message.resources?.length)?.page_identity;

context.history.pushState({}, "", "/lesson-2");
const navigationIndex = messages.findIndex(message => message.navigation && message.page_url === "https://course.example.com/lesson-2");
assert.ok(navigationIndex >= 0);
assert.notEqual(messages[navigationIndex].page_identity, oldIdentity);

vm.runInContext('pageMessageListener({ source: window, data: { source: "learnnote-content-ready" } })', context);
const afterNavigation = messages.slice(navigationIndex + 1).flatMap(message => message.resources || []);
assert.equal(afterNavigation.some(item => item.url === "https://cdn.example.com/lesson-1.mp4"), false);

context.__playInfo = { videoUrl: "https://cdn.example.com/lesson-2.mp4" };
vm.runInContext('pageMessageListener({ source: window, data: { source: "learnnote-content-ready" } })', context);
const currentResource = messages.flatMap(message => message.resources || []).find(item => item.url === "https://cdn.example.com/lesson-2.mp4");
assert.ok(currentResource);
assert.equal(currentResource.page_url, "https://course.example.com/lesson-2");
assert.equal(currentResource.page_identity, messages.at(-1).page_identity);
