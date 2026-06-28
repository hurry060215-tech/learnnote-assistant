import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function listener() {
  return { addListener() {} };
}

let onMessage = null;
const downloads = [];

const context = {
  console,
  Date,
  URL,
  chrome: {
    webRequest: {
      onBeforeSendHeaders: listener(),
      onHeadersReceived: listener(),
      onBeforeRedirect: listener(),
      onCompleted: listener(),
      onErrorOccurred: listener()
    },
    tabs: {
      onRemoved: listener(),
      onUpdated: listener(),
      query() {}
    },
    action: { onClicked: listener() },
    runtime: {
      lastError: null,
      onMessage: {
        addListener(handler) {
          onMessage = handler;
        }
      }
    },
    webNavigation: { getAllFrames() {} },
    sidePanel: { open() {} },
    scripting: { executeScript() {} },
    cookies: { getAll() {} },
    downloads: {
      download(options, callback) {
        downloads.push(options);
        callback(42);
      }
    }
  }
};

vm.createContext(context);
const backgroundCode = await readFile(new URL("../background.js", import.meta.url), "utf8");
vm.runInContext(backgroundCode, context);

assert.equal(typeof onMessage, "function");

const validResponse = await new Promise(resolve => {
  const keepAlive = onMessage(
    {
      type: "download-task-export",
      url: "http://127.0.0.1:8765/api/tasks/task-1/exports/media"
    },
    {},
    resolve
  );
  assert.equal(keepAlive, true);
});

assert.equal(validResponse.ok, true);
assert.equal(validResponse.downloadId, 42);
assert.equal(downloads.length, 1);
assert.equal(downloads[0].url, "http://127.0.0.1:8765/api/tasks/task-1/exports/media");
assert.equal(downloads[0].saveAs, false);

const previewResponse = await new Promise(resolve => {
  onMessage(
    {
      type: "download-task-export",
      url: "http://127.0.0.1:8765/api/tasks/task-1/media"
    },
    {},
    resolve
  );
});

assert.equal(previewResponse.ok, false);
assert.match(previewResponse.error, /LearnNote/);
assert.equal(downloads.length, 1);

const invalidResponse = await new Promise(resolve => {
  onMessage(
    {
      type: "download-task-export",
      url: "https://evil.example.com/api/tasks/task-1/exports/media"
    },
    {},
    resolve
  );
});

assert.equal(invalidResponse.ok, false);
assert.match(invalidResponse.error, /LearnNote/);
assert.equal(downloads.length, 1);
