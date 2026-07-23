import vm from "node:vm";
import { readFile } from "node:fs/promises";

function classList() {
  const values = new Set();
  return {
    add(...items) { items.forEach(item => values.add(item)); },
    remove(...items) { items.forEach(item => values.delete(item)); },
    toggle(item, force) {
      if (force === true) values.add(item);
      else if (force === false) values.delete(item);
      else if (values.has(item)) values.delete(item);
      else values.add(item);
    },
    contains(item) { return values.has(item); }
  };
}

function element() {
  const listeners = new Map();
  const attributes = new Map();
  return {
    dataset: {},
    style: {},
    classList: classList(),
    textContent: "",
    innerHTML: "",
    hidden: false,
    disabled: false,
    value: "",
    addEventListener(type, callback) { listeners.set(type, callback); },
    dispatch(type, event = {}) { return listeners.get(type)?.({ preventDefault() {}, target: this, ...event }); },
    setAttribute(name, value) { attributes.set(name, String(value)); },
    getAttribute(name) { return attributes.get(name) ?? null; },
    querySelector() { return null; }
  };
}

export async function createSidepanelHarness({ contexts = [], preflight = null, start = null, health = null } = {}) {
  const selectors = [
    "#connectionCard", "#connectionTitle", "#connectionDetail", "#openClientButton", "#openClientBrand",
    "#refreshButton", "#platformLabel", "#playingBadge", "#videoTitle", "#videoMeta", "#integrityGrid",
    "#candidateCount", "#durationValue", "#estimateValue", "#preflightMessage", "#sendButton",
    "#handoffProgress", "#handoffStatus", "#handoffPercent", "#openTaskButton"
  ];
  const elements = new Map(selectors.map(selector => [selector, element()]));
  const integrityItems = new Map(["video", "audio", "subtitle"].map(kind => {
    const item = element();
    const strong = element();
    item.querySelector = selector => selector === "strong" ? strong : null;
    item.strong = strong;
    return [kind, item];
  }));
  elements.get("#integrityGrid").querySelector = selector => {
    const match = /data-kind="([^"]+)"/.exec(selector);
    return match ? integrityItems.get(match[1]) || null : null;
  };
  const progressBar = element();
  elements.get("#handoffProgress").querySelector = selector => selector === "span" ? progressBar : null;
  const clientLinks = [element(), element()];
  clientLinks[0].dataset.clientView = "settings";
  clientLinks[1].dataset.clientView = "diagnostics";

  const sentMessages = [];
  const openedTabs = [];
  let contextIndex = 0;
  let runtimeListener = null;
  const fetchCalls = [];
  const documentStub = {
    querySelector(selector) { return elements.get(selector) || null; },
    querySelectorAll(selector) { return selector === "[data-client-view]" ? clientLinks : []; }
  };
  const context = {
    console,
    Date,
    URL,
    AbortController,
    document: documentStub,
    location: { href: "chrome-extension://learnnote/sidepanel.html" },
    window: { addEventListener() {}, open() { return true; } },
    setTimeout,
    clearTimeout,
    fetch: async (url, options = {}) => {
      fetchCalls.push({ url: String(url), options });
      if (String(url).endsWith("/health")) {
        if (health instanceof Error) throw health;
        return { ok: true, json: async () => health || ({ app_version: "0.1.38" }) };
      }
      if (String(url).endsWith("/api/desktop/focus")) {
        return { ok: true, json: async () => ({ ok: true, available: true }) };
      }
      throw new Error(`Unexpected fetch: ${url}`);
    },
    chrome: {
      storage: { local: { async get(defaults) { return defaults; }, async set() {} } },
      tabs: { async create(options) { openedTabs.push(options); return options; } },
      runtime: {
        onMessage: { addListener(listener) { runtimeListener = listener; } },
        async sendMessage(message) {
          sentMessages.push(message);
          if (message.type === "get-current-context") {
            const value = contexts[Math.min(contextIndex, Math.max(0, contexts.length - 1))] || {};
            contextIndex += 1;
            return structuredClone(value);
          }
          if (message.type === "preflight-current-page") {
            return structuredClone(preflight || { report: { ok: true, ready: true, message: "预检通过" } });
          }
          if (message.type === "start-current-task") {
            return structuredClone(start || { task_id: "abc123def456" });
          }
          throw new Error(`Unexpected message: ${message.type}`);
        }
      }
    }
  };
  vm.createContext(context);
  const code = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
  vm.runInContext(code, context);
  await new Promise(resolve => setTimeout(resolve, 20));
  return {
    context,
    api: context.__learnnoteSidepanel,
    elements,
    integrityItems,
    progressBar,
    clientLinks,
    sentMessages,
    openedTabs,
    fetchCalls,
    emit(message) { runtimeListener?.(message); }
  };
}

export function videoContext({ tabId = 7, bvid = "BV1ABCDEF123", title = "示例课程", resource = "https://cdn.example.com/video.m4s?token=one", audio = true, subtitle = true } = {}) {
  const pageUrl = `https://www.bilibili.com/video/${bvid}/?p=1&utm_source=test`;
  const resources = [{ url: resource, kind: "video", score: 100, mime: "video/mp4" }];
  if (audio) resources.push({ url: "https://cdn.example.com/audio.m4s?token=one", kind: "audio", score: 90, mime: "audio/mp4" });
  if (subtitle) resources.push({ url: "https://cdn.example.com/subtitle.vtt", kind: "subtitle", score: 70, mime: "text/vtt" });
  return {
    tab: { id: tabId, url: pageUrl, title },
    page: {
      title,
      page_url: pageUrl,
      active_video: { src: resource, duration: 631, current_time: 12, paused: false },
      browser_subtitles: subtitle ? [{ start: 0, end: 2, text: "字幕" }] : []
    },
    resources
  };
}
