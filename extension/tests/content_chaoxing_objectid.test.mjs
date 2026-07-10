import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

class FakeElement {
  constructor(tagName, attributes = {}, children = []) {
    this.tagName = tagName.toUpperCase();
    this.nodeType = 1;
    this.attributes = attributes;
    this.children = children;
    this.src = attributes.src || "";
    this.shadowRoot = null;
  }

  getAttribute(name) {
    return this.attributes[name] || "";
  }

  querySelectorAll(selector) {
    const selectors = selector.split(",").map(item => item.trim());
    const results = [];
    const visit = node => {
      for (const child of node.children || []) {
        if (selectors.some(item => item === "*" || item === "iframe[src]" && child.tagName === "IFRAME" && child.src)) results.push(child);
        visit(child);
      }
    };
    visit(this);
    return results;
  }

  querySelector() { return null; }
  matches() { return false; }
  addEventListener() {}
}

const objectId = "0ad0c79e7d8aa25d0e39360a4a30d6ec";
const iframe = new FakeElement("iframe", {
  class: "ans-attach-online ans-insertvideo-online",
  src: "https://mooc1.chaoxing.com/ananas/modules/video/index.html?v=2026-0708-1025",
  objectid: objectId,
  data: JSON.stringify({ objectid: objectId, name: "lesson" })
});
const html = new FakeElement("html", {}, [iframe]);
let messageListener = null;
const context = {
  console,
  URL,
  URLSearchParams,
  Node: { ELEMENT_NODE: 1 },
  location: { href: "https://mooc1.chaoxing.com/mycourse/studentstudy?chapterId=1" },
  document: {
    title: "Chaoxing lesson",
    readyState: "complete",
    documentElement: html,
    body: { innerText: "lesson" },
    querySelectorAll(selector) { return html.querySelectorAll(selector); },
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
  atob: value => Buffer.from(value, "base64").toString("binary"),
  setTimeout() { return 0; },
  clearTimeout() {},
  setInterval() { return 0; }
};
context.window = context;
context.window.addEventListener = () => {};
context.window.postMessage = () => {};

vm.createContext(context);
const contentCode = await readFile(new URL("../content.js", import.meta.url), "utf8");
vm.runInContext(contentCode, context);

let response = null;
messageListener({ type: "collect-page-data" }, {}, data => { response = data; });

const status = response.resources.find(item => item.url === `https://mooc1.chaoxing.com/ananas/status/${objectId}?k=&flag=normal`);
assert.ok(status, "expected objectid iframe to create a direct ananas status candidate");
assert.equal(status.kind, "video");
assert.equal(status.source, "domHint");
assert.equal(status.is_main_video, true);
assert.equal(status.playback_match, "objectid-status");
assert.equal(status.frame_url, iframe.src);
assert.equal(status.request_headers.Referer, context.location.href);
