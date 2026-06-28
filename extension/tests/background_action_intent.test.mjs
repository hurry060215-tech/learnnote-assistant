import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

let actionClick = null;
const storageWrites = [];
const sidePanelOpens = [];
const runtimeMessages = [];

function listener(callbackName = "") {
  return {
    addListener(callback) {
      if (callbackName === "action") actionClick = callback;
    }
  };
}

const context = {
  console,
  Date,
  URL,
  chrome: {
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
    action: { onClicked: listener("action") },
    runtime: {
      onMessage: listener(),
      sendMessage(message) {
        runtimeMessages.push(message);
        return Promise.resolve();
      }
    },
    webNavigation: { getAllFrames() {} },
    sidePanel: {
      open(options) {
        sidePanelOpens.push(options);
      }
    },
    scripting: { executeScript() {} },
    cookies: { getAll() {} },
    storage: {
      local: {
        set(value) {
          storageWrites.push(value);
        }
      }
    }
  }
};

vm.createContext(context);
const backgroundCode = await readFile(new URL("../background.js", import.meta.url), "utf8");
vm.runInContext(backgroundCode, context);

assert.equal(typeof actionClick, "function");

actionClick({ id: 123, url: "https://course.example.com/lesson" });

assert.equal(sidePanelOpens.length, 1);
assert.equal(sidePanelOpens[0].tabId, 123);
assert.equal(storageWrites.length, 1);
assert.equal(storageWrites[0].pendingSidePanelIntent.action, "summarize-current-video");
assert.equal(storageWrites[0].pendingSidePanelIntent.tabId, 123);
assert.equal(typeof storageWrites[0].pendingSidePanelIntent.createdAt, "number");
assert.equal(runtimeMessages.length, 1);
assert.equal(runtimeMessages[0].type, "sidepanel-action-intent");
assert.equal(runtimeMessages[0].intent.action, "summarize-current-video");
assert.equal(runtimeMessages[0].intent.tabId, 123);
