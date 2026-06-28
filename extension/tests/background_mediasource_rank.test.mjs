import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function listener() {
  return { addListener() {} };
}

const now = Date.now();
const context = {
  console,
  Date: class extends Date {
    static now() {
      return now;
    }
  },
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
    runtime: { onMessage: listener() },
    webNavigation: { getAllFrames() {} },
    sidePanel: { open() {} },
    scripting: { executeScript() {} },
    cookies: { getAll() {} }
  }
};

vm.createContext(context);
const backgroundCode = await readFile(new URL("../background.js", import.meta.url), "utf8");
vm.runInContext(backgroundCode, context);

const hinted = context.withPlaybackHints({
  url: "https://cdn.example.com/mse/lesson.mp4",
  source: "pageHookMediaSource",
  kind: "video",
  mime: "video/mp4",
  score: 10,
  time_stamp: now - 1000
}, {
  page_url: "https://course.example.com/player",
  active_video: {
    src: "blob:https://course.example.com/mse-1",
    frame_id: 0,
    paused: false
  }
});

assert.equal(hinted.playback_match, "blob-source");
assert.equal(hinted.is_main_video, true);
assert.ok(hinted.score >= 100, "expected recent pageHookMediaSource candidates to receive blob playback boost");
