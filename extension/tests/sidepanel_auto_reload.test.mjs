import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const elements = new Map();
const makeElement = () => ({
  addEventListener() {},
  classList: { add() {}, remove() {}, toggle() {} },
  querySelector() { return null; },
  style: {},
  dataset: {},
  value: "",
  textContent: "",
  innerHTML: "",
  disabled: false,
  hidden: false,
  onclick: null,
  onchange: null,
  files: []
});
const document = {
  body: { dataset: {} },
  hidden: false,
  addEventListener() {},
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, makeElement());
    return elements.get(selector);
  },
  querySelectorAll() { return []; }
};

const stored = {};
let reloads = 0;
const context = {
  console,
  document,
  location: { href: "chrome-extension://learnnote/sidepanel.html" },
  navigator: { clipboard: { async writeText() {} } },
  window: { open() {}, addEventListener() {} },
  FormData: class FormData {},
  URL,
  fetch: async url => {
    const value = String(url);
    if (value.endsWith("/api/extension/heartbeat")) return { ok: true, json: async () => ({ ok: true }) };
    if (value.endsWith("/health")) return { ok: true, json: async () => ({ app_version: "0.1.35", protocol_version: 1, ffmpeg: true }) };
    if (value.endsWith("/api/tasks")) return { ok: true, json: async () => ({ tasks: [] }) };
    if (value.endsWith("/api/preferences")) return { ok: true, json: async () => ({}) };
    throw new Error(`unexpected fetch: ${url}`);
  },
  chrome: {
    storage: {
      local: {
        async get(defaults) { return { ...defaults, ...stored }; },
        async set(value) { Object.assign(stored, value); },
        async remove(key) { delete stored[key]; }
      }
    },
    runtime: {
      getManifest() { return { version: "0.1.34" }; },
      reload() { reloads += 1; },
      async sendMessage(message) {
        if (message.type === "get-current-context") return { tab: { id: 1 }, page: null, resources: [] };
        throw new Error(`unexpected message: ${message.type}`);
      },
      onMessage: { addListener() {} }
    },
    tabs: { create() {} }
  },
  setTimeout,
  clearTimeout
};
context.window = { ...context.window, location: context.location };

vm.createContext(context);
const code = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
vm.runInContext(code, context);
await new Promise(resolve => setTimeout(resolve, 400));

assert.equal(reloads, 1);
assert.equal(stored.lastAutoReloadForAppVersion, "0.1.35");
assert.match(elements.get("#backendStatus").textContent, /正在加载新版扩展/);
await context.health();
await new Promise(resolve => setTimeout(resolve, 350));
assert.equal(reloads, 1, "the same client version must not cause an automatic reload loop");
assert.equal(context.isNewerVersion("0.1.35", "0.1.34"), true);
assert.equal(context.isNewerVersion("0.1.34", "0.1.34"), false);
assert.equal(context.isNewerVersion("0.1.33", "0.1.34"), false);
