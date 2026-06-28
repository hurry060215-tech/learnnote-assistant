import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

class FakeVideo {
  constructor() {
    this.tagName = "VIDEO";
    this.nodeType = 1;
    this.children = [];
    this.src = "";
    this.currentSrc = "";
    this.type = "";
    this.currentTime = 18;
    this.duration = 90;
    this.paused = false;
    this.ended = false;
    this.readyState = 4;
    this.videoWidth = 1280;
    this.videoHeight = 720;
    this.clientWidth = 1280;
    this.clientHeight = 720;
    this.textTracks = [];
    this.srcObject = {
      constructor: { name: "MediaStream" },
      getTracks() {
        return [{ kind: "video" }, { kind: "audio" }];
      }
    };
  }

  querySelectorAll() {
    return [];
  }

  querySelector() {
    return null;
  }

  matches(selector) {
    return selector.split(",").map(item => item.trim()).includes("video");
  }

  addEventListener() {}
}

const video = new FakeVideo();
let messageListener = null;
const context = {
  console,
  URL,
  Node: { ELEMENT_NODE: 1 },
  location: { href: "https://course.example.com/stream-lesson" },
  document: {
    title: "MediaStream lesson",
    readyState: "complete",
    documentElement: { children: [video], nodeType: 1 },
    body: { innerText: "Stream lesson text" },
    querySelectorAll(selector) {
      return selector === "video" || selector === "*" ? [video] : [];
    },
    addEventListener() {}
  },
  window: null,
  chrome: {
    runtime: {
      onMessage: {
        addListener(listener) {
          messageListener = listener;
        }
      },
      sendMessage() {
        return Promise.resolve();
      }
    }
  },
  MutationObserver: class {
    observe() {}
  },
  performance: {
    getEntriesByType() {
      return [];
    }
  },
  setTimeout() {
    return 0;
  },
  clearTimeout() {},
  setInterval() {
    return 0;
  }
};

context.window = context;
context.window.addEventListener = () => {};
context.window.postMessage = () => {};

vm.createContext(context);
const contentCode = await readFile(new URL("../content.js", import.meta.url), "utf8");
vm.runInContext(contentCode, context);

let response = null;
messageListener({ type: "collect-page-data" }, {}, data => {
  response = data;
});

assert.equal(response.active_video.src, "");
assert.equal(response.active_video.src_object, true);
assert.equal(response.active_video.src_object_type, "MediaStream");
assert.equal(response.active_video.src_object_track_count, 2);
assert.equal(response.active_video.src_object_video_tracks, 1);
assert.equal(response.active_video.src_object_audio_tracks, 1);
assert.equal(response.active_video.paused, false);
assert.equal(response.resources.length, 0);
