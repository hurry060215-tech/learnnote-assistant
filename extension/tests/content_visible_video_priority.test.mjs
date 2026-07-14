import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function fakeVideo({ src, paused = false, width, height, left = 0, top = 0, hidden = false, duration = 600 }) {
  return {
    currentSrc: src,
    src: "",
    paused,
    ended: false,
    readyState: 4,
    currentTime: 30,
    duration,
    videoWidth: width,
    videoHeight: height,
    clientWidth: width,
    clientHeight: height,
    hidden,
    querySelector() { return null; },
    querySelectorAll() { return []; },
    getAttribute() { return ""; },
    getBoundingClientRect() {
      return { left, top, right: left + width, bottom: top + height, width, height };
    }
  };
}

let messageListener = null;
const context = {
  console,
  URL,
  Node: { ELEMENT_NODE: 1 },
  location: { href: "https://course.example.com/lesson" },
  document: {
    title: "Visible video priority",
    readyState: "complete",
    documentElement: { clientWidth: 1440, clientHeight: 900, querySelectorAll() { return []; } },
    body: { innerText: "" },
    querySelectorAll() { return []; },
    addEventListener() {}
  },
  window: null,
  chrome: {
    runtime: {
      onMessage: { addListener(listener) { messageListener = listener; } },
      sendMessage() { return Promise.resolve(); }
    }
  },
  MutationObserver: class { observe() {} },
  performance: { getEntriesByType() { return []; } },
  setTimeout() { return 0; },
  clearTimeout() {},
  setInterval() { return 0; }
};
context.window = context;
context.window.innerWidth = 1440;
context.window.innerHeight = 900;
context.window.getComputedStyle = element => ({
  display: element.hidden ? "none" : "block",
  visibility: "visible",
  opacity: "1"
});
context.window.addEventListener = () => {};
context.window.postMessage = () => {};

vm.createContext(context);
const contentCode = await readFile(new URL("../content.js", import.meta.url), "utf8");
vm.runInContext(contentCode, context);

assert.ok(messageListener, "expected content script message listener");

const hiddenAutoplay = fakeVideo({
  src: "https://activity.hdslb.com/promo.mp4",
  width: 1920,
  height: 1080,
  hidden: true,
  duration: 12
});
const smallAutoplay = fakeVideo({
  src: "https://ads.obeebee.com/spot.mp4",
  width: 320,
  height: 180,
  duration: 15
});
const lesson = fakeVideo({
  src: "https://cdn.example.com/course/lesson.mp4",
  width: 1280,
  height: 720,
  duration: 1800
});

const selected = context.pickMainVideo([
  { video: hiddenAutoplay, index: 0 },
  { video: smallAutoplay, index: 1 },
  { video: lesson, index: 2 }
]);

assert.equal(selected.video, lesson);
const evidence = context.elementVisibilityEvidence(lesson);
assert.equal(evidence.visibility, "visible");
assert.equal(evidence.is_visible, true);
assert.equal(evidence.visible_area, 1280 * 720);
