import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const listeners = {};
const alarms = [];
const requests = [];

function listener(name = "") {
  return {
    addListener(callback) {
      if (name) listeners[name] = callback;
    }
  };
}

const context = {
  console,
  URL,
  Date,
  Map,
  Set,
  Promise,
  setTimeout,
  clearTimeout,
  fetch: async (url, options = {}) => {
    requests.push({ url, options });
    return { ok: true };
  },
  chrome: {
    alarms: {
      create(name, options) {
        alarms.push({ name, options });
      },
      onAlarm: listener("alarm")
    },
    runtime: {
      getManifest() {
        return { version: "9.8.7" };
      },
      onInstalled: listener("installed"),
      onStartup: listener("startup"),
      onMessage: listener("message"),
      sendMessage() {}
    },
    storage: {
      local: {
        async get() {
          return { backendUrl: "http://127.0.0.1:8765" };
        },
        async set() {}
      }
    },
    webRequest: {
      onBeforeSendHeaders: listener(),
      onHeadersReceived: listener(),
      onCompleted: listener(),
      onBeforeRedirect: listener(),
      onErrorOccurred: listener()
    },
    tabs: {
      onRemoved: listener(),
      onActivated: listener(),
      onUpdated: listener(),
      query() {}
    },
    action: { onClicked: listener() },
    webNavigation: {
      getAllFrames() {},
      onHistoryStateUpdated: listener()
    },
    sidePanel: { open() {} },
    scripting: { executeScript() {} },
    cookies: { getAll() {} },
    downloads: { download() {} }
  }
};

vm.createContext(context);
const backgroundCode = await readFile(new URL("../background.js", import.meta.url), "utf8");
vm.runInContext(backgroundCode, context);
await new Promise(resolve => setImmediate(resolve));

assert.equal(alarms.length, 1);
assert.equal(alarms[0].name, "learnnote-backend-heartbeat");
assert.equal(alarms[0].options.periodInMinutes, 0.5);
assert.equal(requests.length, 1);
assert.equal(requests[0].url, "http://127.0.0.1:8765/api/extension/heartbeat");
assert.deepEqual(JSON.parse(requests[0].options.body), {
  extension_version: "9.8.7",
  protocol_version: 1,
  source: "background"
});

listeners.alarm({ name: "unrelated" });
await new Promise(resolve => setImmediate(resolve));
assert.equal(requests.length, 1);

listeners.alarm({ name: "learnnote-backend-heartbeat" });
await new Promise(resolve => setImmediate(resolve));
assert.equal(requests.length, 2);
