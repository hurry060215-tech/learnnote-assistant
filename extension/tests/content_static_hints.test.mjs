import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function selectorMatches(element, selector) {
  const item = selector.trim();
  if (item === "*") return true;
  const attrOnly = item.match(/^\[([a-z0-9-]+)\]$/i);
  if (attrOnly) return Boolean(element.getAttribute(attrOnly[1]));
  const attrMatch = item.match(/^([a-z0-9-]+)\[([a-z0-9-]+)\]$/i);
  if (attrMatch) {
    return element.tagName.toLowerCase() === attrMatch[1].toLowerCase() && Boolean(element.getAttribute(attrMatch[2]));
  }
  return element.tagName.toLowerCase() === item.toLowerCase();
}

function collectDescendants(root, selector) {
  const selectors = selector.split(",");
  const results = [];

  function visit(node) {
    for (const child of node.children || []) {
      if (selectors.some(item => selectorMatches(child, item))) results.push(child);
      visit(child);
    }
  }

  visit(root);
  return results;
}

class FakeElement {
  constructor(tagName, attributes = {}, children = []) {
    this.tagName = tagName.toUpperCase();
    this.nodeType = 1;
    this.children = children;
    this.attributes = attributes;
    this.textContent = attributes.textContent || "";
    this.src = attributes.src || "";
    this.href = attributes.href || "";
    this.type = attributes.type || "";
    this.shadowRoot = null;
  }

  getAttribute(name) {
    return this.attributes[name] || "";
  }

  querySelectorAll(selector) {
    return collectDescendants(this, selector);
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  matches(selector) {
    return selector.split(",").some(item => selectorMatches(this, item));
  }

  addEventListener() {}
}

const packedDash = Buffer.from("https://cdn.example.com/static/manifest.mpd?token=b64", "utf8").toString("base64");

const player = new FakeElement("div", {
  "data-play-url": "https%3A%2F%2Fcdn.example.com%2Fstatic%2Fmaster.m3u8%3Ftoken%3Dattr"
});
const packedPlayer = new FakeElement("div", {
  "data-video-url": packedDash
});
const script = new FakeElement("script", {
  textContent: "window.__player={videoUrl:'https%3A%2F%2Fcdn.example.com%2Fstatic%2Flesson.mp4%3Ftoken%3Dscript', flvUrl:'https://cdn.example.com/static/live.flv?token=script'};"
});
const plainEncodedScript = new FakeElement("script", {
  textContent: "window.__payload='https%3A%2F%2Fcdn.example.com%2Fstatic%2Fplain-master.m3u8%3Ftoken%3Dplain%26uid%3D1';"
});
const onclickPlayer = new FakeElement("button", {
  onclick: "openPlayer('https%3A%2F%2Fcdn.example.com%2Fstatic%2Fonclick-master.m3u8%3Ftoken%3Dclick')"
});
const paramPlayer = new FakeElement("div", {
  "data-params": "objectid=ignored&play=https%3A%2F%2Fcdn.example.com%2Fstatic%2Fparam-lesson.mp4%3Ftoken%3Dparam"
});
const html = new FakeElement("html", {}, [player, packedPlayer, onclickPlayer, paramPlayer, script, plainEncodedScript]);

let messageListener = null;
const context = {
  console,
  URL,
  Node: { ELEMENT_NODE: 1 },
  location: { href: "https://course.example.com/lesson" },
  document: {
    title: "Static hints lesson",
    readyState: "complete",
    documentElement: html,
    body: { innerText: "Course body" },
    querySelectorAll(selector) {
      return collectDescendants({ children: [html] }, selector);
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
  atob: value => Buffer.from(value, "base64").toString("binary"),
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

const hls = response.resources.find(item => item.url === "https://cdn.example.com/static/master.m3u8?token=attr");
const dash = response.resources.find(item => item.url === "https://cdn.example.com/static/manifest.mpd?token=b64");
const video = response.resources.find(item => item.url === "https://cdn.example.com/static/lesson.mp4?token=script");
const flv = response.resources.find(item => item.url === "https://cdn.example.com/static/live.flv?token=script");
const plainHls = response.resources.find(item => item.url === "https://cdn.example.com/static/plain-master.m3u8?token=plain&uid=1");
const onclickHls = response.resources.find(item => item.url === "https://cdn.example.com/static/onclick-master.m3u8?token=click");
const paramVideo = response.resources.find(item => item.url === "https://cdn.example.com/static/param-lesson.mp4?token=param");

assert.ok(hls, "expected data-play-url media hint to expose encoded HLS URL");
assert.equal(hls.kind, "hls");
assert.equal(hls.source, "domHint");
assert.match(hls.label, /data-play-url/);

assert.ok(dash, "expected base64 data-video-url media hint to expose DASH manifest");
assert.equal(dash.kind, "dash");
assert.equal(dash.source, "domHint");
assert.match(dash.label, /data-video-url/);

assert.ok(video, "expected inline script media hint to expose encoded mp4 URL");
assert.equal(video.kind, "video");
assert.equal(video.source, "scriptHint");
assert.match(video.label, /videoUrl/);

assert.ok(flv, "expected inline script media hint to expose FLV URL");
assert.equal(flv.kind, "video");
assert.equal(flv.source, "scriptHint");
assert.match(flv.label, /flvUrl/);

assert.ok(plainHls, "expected inline script encoded URL scan to expose HLS URL without a media field name");
assert.equal(plainHls.kind, "hls");
assert.equal(plainHls.source, "scriptHint");
assert.match(plainHls.label, /encoded url/);

assert.ok(onclickHls, "expected onclick handler scan to expose embedded encoded HLS URL");
assert.equal(onclickHls.kind, "hls");
assert.equal(onclickHls.source, "domHint");
assert.match(onclickHls.label, /onclick encoded url/);

assert.ok(paramVideo, "expected data-params scan to expose embedded encoded mp4 URL");
assert.equal(paramVideo.kind, "video");
assert.equal(paramVideo.source, "domHint");
assert.match(paramVideo.label, /data-params encoded url/);
