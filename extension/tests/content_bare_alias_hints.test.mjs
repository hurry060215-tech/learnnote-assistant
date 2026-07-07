import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function selectorMatches(element, selector) {
  const item = selector.trim();
  if (item === "*") return true;
  const attrOnly = item.match(/^\[([a-z0-9-]+)\]$/i);
  if (attrOnly) return Boolean(element.getAttribute(attrOnly[1]));
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

  matches(selector) {
    return selector.split(",").some(item => selectorMatches(this, item));
  }

  addEventListener() {}
}

const bareAliasScript = new FakeElement("script", {
  textContent: `window.__bareAliasPlayer={
    backup:"/backup?id=bare-backup&token=ok",
    main:"/main?id=bare-main&token=ok",
    manifest:"/manifest?id=bare-manifest&token=ok"
  };`
});
const html = new FakeElement("html", {}, [bareAliasScript]);

let messageListener = null;
const context = {
  console,
  URL,
  Node: { ELEMENT_NODE: 1 },
  location: { href: "https://course.example.com/lesson" },
  document: {
    title: "Bare alias lesson",
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
messageListener({ type: "collect-page-data" }, {}, data => {
  response = data;
});

const backup = response.resources.find(item => item.url === "https://course.example.com/backup?id=bare-backup&token=ok");
const main = response.resources.find(item => item.url === "https://course.example.com/main?id=bare-main&token=ok");
const manifest = response.resources.find(item => item.url === "https://course.example.com/manifest?id=bare-manifest&token=ok");

assert.ok(backup, "expected bare backup field to expose extensionless playback endpoint");
assert.equal(backup.kind, "video");
assert.equal(backup.source, "scriptHint");

assert.ok(main, "expected bare main field to expose extensionless playback endpoint");
assert.equal(main.kind, "video");
assert.equal(main.source, "scriptHint");

assert.ok(manifest, "expected bare manifest field to expose extensionless playback endpoint");
assert.equal(manifest.kind, "video");
assert.equal(manifest.source, "scriptHint");
