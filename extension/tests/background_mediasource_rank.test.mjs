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

const sorted = [
  {
    url: "https://cdn.example.com/archive-or-ad.mp4",
    source: "webRequest",
    kind: "video",
    score: 100,
    time_stamp: now + 2000
  },
  {
    url: "https://cdn.example.com/current-lesson.mp4",
    source: "pageHookBlobSource",
    kind: "video",
    score: 42,
    playback_match: "blob-source",
    blob_url: "blob:https://course.example.com/mse-1",
    time_stamp: now
  }
].sort(context.compareResourceCandidates);

assert.equal(sorted[0].url, "https://cdn.example.com/current-lesson.mp4");

const sourceElementSorted = [
  {
    url: "https://cdn.example.com/preload-or-ad.mp4",
    source: "webRequest",
    kind: "video",
    score: 100,
    time_stamp: now + 3000
  },
  {
    url: "https://cdn.example.com/current-source.mp4",
    source: "dom",
    kind: "video",
    score: 82,
    playback_match: "source-element",
    is_main_video: true,
    time_stamp: now
  }
].sort(context.compareResourceCandidates);

assert.equal(sourceElementSorted[0].url, "https://cdn.example.com/current-source.mp4");
assert.equal(sourceElementSorted[0].playback_match, "source-element");

const playableApiSorted = [
  {
    url: "https://cdn.example.com/tracker.gif",
    source: "webRequest",
    kind: "unknown",
    score: 95,
    request_type: "image",
    time_stamp: now + 4000
  },
  {
    url: "https://mooc1.chaoxing.com/ananas/status/play?id=course-video",
    source: "webRequest",
    kind: "unknown",
    score: 10,
    request_type: "xmlhttprequest",
    method: "POST",
    request_body: { content: "objectid=abc&dtoken=def", type: "form" },
    time_stamp: now
  }
].sort(context.compareResourceCandidates);

assert.equal(playableApiSorted[0].url, "https://mooc1.chaoxing.com/ananas/status/play?id=course-video");
assert.ok(context.playableEndpointScore(playableApiSorted[0]) >= 90, "expected replayable playback API endpoint to receive a high score");
