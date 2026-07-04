import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const elements = new Map();
const makeElement = () => ({
  addEventListener() {},
  classList: { add() {}, remove() {}, toggle() {} },
  querySelector() { return null; },
  style: {},
  dataset: {},
  value: "",
  textContent: "",
  innerHTML: "",
  disabled: false,
  onclick: null,
  onchange: null,
  files: []
});

const documentStub = {
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, makeElement());
    return elements.get(selector);
  },
  querySelectorAll() {
    return [];
  }
};

const stored = {
  backendUrl: "https://evil.example",
  modelSettings: {
    llm_provider: "openrouter",
    llm_model: "openai/gpt-4.1-mini",
    llm_base_url: "https://openrouter.ai/api/v1",
    transcriber: "faster-whisper",
    whisper_model: "small"
  }
};
const calls = { storageSet: [], fetchUrls: [] };
let promptCalled = false;

const context = {
  console,
  document: documentStub,
  location: { href: "chrome-extension://learnnote/sidepanel.html" },
  navigator: { clipboard: { writeText() {} } },
  window: { open() {} },
  FormData: class FormData {},
  URL,
  prompt: () => {
    promptCalled = true;
    throw new Error("prompt should not be used for backend settings");
  },
  fetch: async url => {
    calls.fetchUrls.push(String(url));
    const value = String(url);
    if (value.endsWith("/health")) {
      return { json: async () => ({ ffmpeg: true }) };
    }
    if (value.endsWith("/api/tasks")) {
      return { json: async () => ({ tasks: [] }) };
    }
    throw new Error(`unexpected fetch: ${url}`);
  },
  chrome: {
    storage: {
      local: {
        async get(defaults) {
          return { ...defaults, ...stored };
        },
        async set(value) {
          calls.storageSet.push(value);
          Object.assign(stored, value);
        },
        async remove(key) {
          delete stored[key];
        }
      }
    },
    runtime: {
      async sendMessage(message) {
        if (message.type === "get-current-context") {
          return { page: null, resources: [] };
        }
        throw new Error(`unexpected message: ${message.type}`);
      },
      onMessage: { addListener() {} }
    },
    tabs: {
      create() {}
    }
  },
  setTimeout,
  clearTimeout
};
context.window = { ...context.window, location: context.location };

vm.createContext(context);
const sidepanelCode = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
const sidepanelHtml = await readFile(new URL("../sidepanel.html", import.meta.url), "utf8");
vm.runInContext(sidepanelCode, context);

await new Promise(resolve => setTimeout(resolve, 0));

assert.match(sidepanelHtml, /value="gemini">Google Gemini/);
assert.match(sidepanelHtml, /value="dashscope">/);
assert.match(sidepanelHtml, /value="siliconflow">SiliconFlow/);
assert.match(sidepanelHtml, /id="backendSettingsPanel"/);
assert.match(sidepanelHtml, /id="backendUrlInput"/);
assert.match(sidepanelHtml, /id="saveBackendSettingsButton"/);
assert.equal(elements.get("#llmProvider").value, "openrouter");
assert.equal(elements.get("#llmModel").value, "openai/gpt-4.1-mini");
assert.equal(elements.get("#llmBaseUrl").value, "https://openrouter.ai/api/v1");
assert.equal(elements.get("#transcriber").value, "faster-whisper");
assert.equal(elements.get("#whisperModel").value, "small");
assert.match(elements.get("#backendStatus").innerHTML, /backend-status-chip asr/);
assert.match(elements.get("#backendStatus").innerHTML, /本地 faster-whisper · small/);

assert.equal(context.normalizeBackendUrl("127.0.0.1:8000/"), "http://127.0.0.1:8000");
assert.equal(context.normalizeBackendUrl("localhost:8765/workbench"), "http://localhost:8765");
assert.equal(context.normalizeBackendUrl("https://evil.example"), "");
assert.equal(context.normalizeBackendUrl("ftp://127.0.0.1:8765"), "");
assert.equal(context.normalizeBackendUrl("http://user:pass@127.0.0.1:8765"), "");

assert.equal(context.workbenchUrl("task-default", "frames"), "http://127.0.0.1:8765/?task=task-default&tab=frames");

elements.get("#backendUrlInput").value = "127.0.0.1:8000/";
await context.saveSettings();

assert.equal(calls.storageSet.at(-1).backendUrl, "http://127.0.0.1:8000");
assert.equal(context.workbenchUrl("task-local", "note"), "http://127.0.0.1:8000/?task=task-local&tab=note");
assert.equal(promptCalled, false);

elements.get("#backendSettingsPanel").hidden = true;
context.openBackendSettingsPanel();
assert.equal(elements.get("#backendSettingsPanel").hidden, false);
assert.equal(elements.get("#backendUrlInput").value, "http://127.0.0.1:8000");
elements.get("#backendUrlInput").value = "localhost:8766/workbench";
await context.saveSettings();
assert.equal(calls.storageSet.at(-1).backendUrl, "http://localhost:8766");
assert.equal(elements.get("#backendSettingsPanel").hidden, true);
assert.equal(context.workbenchUrl("task-panel", "note"), "http://localhost:8766/?task=task-panel&tab=note");

calls.storageSet = [];
elements.get("#backendUrlInput").value = "https://evil.example";
await context.saveSettings();

assert.equal(calls.storageSet.length, 0);
assert.equal(context.workbenchUrl("task-local", "note"), "http://localhost:8766/?task=task-local&tab=note");
assert.match(elements.get("#backendStatus").textContent, /127\.0\.0\.1|localhost/);
assert.match(elements.get("#taskMessage").textContent, /本机后端/);

elements.get("#llmProvider").value = "groq";
context.applyModelProviderPreset(true);
elements.get("#llmApiKey").value = "sk-should-not-persist";
await context.saveModelSettings();
const savedModelSettings = calls.storageSet.at(-1).modelSettings;
assert.equal(savedModelSettings.llm_provider, "groq");
assert.equal(savedModelSettings.llm_base_url, "https://api.groq.com/openai/v1");
assert.equal(savedModelSettings.llm_model, "meta-llama/llama-4-scout-17b-16e-instruct");
assert.equal(savedModelSettings.transcriber, "groq");
assert.equal(savedModelSettings.whisper_model, "whisper-large-v3");
assert.equal(Object.hasOwn(savedModelSettings, "llm_api_key"), false);
assert.equal(JSON.stringify(savedModelSettings).includes("sk-should-not-persist"), false);

elements.get("#llmProvider").value = "gemini";
context.applyModelProviderPreset(true);
await context.saveModelSettings();
const savedGeminiSettings = calls.storageSet.at(-1).modelSettings;
assert.equal(savedGeminiSettings.llm_provider, "gemini");
assert.equal(savedGeminiSettings.llm_base_url, "https://generativelanguage.googleapis.com/v1beta/openai/");
assert.equal(savedGeminiSettings.llm_model, "gemini-3.5-flash");
assert.equal(savedGeminiSettings.transcriber, "faster-whisper");
assert.equal(savedGeminiSettings.whisper_model, "small");
elements.get("#llmApiKey").value = "";
context.updateHealthVisionStatus({ ffmpeg: true, vision_model_configured: false });
assert.match(elements.get("#backendStatus").innerHTML, /待填 · Gemini/);
assert.match(elements.get("#backendStatus").innerHTML, /本地 faster-whisper · small/);
assert.match(elements.get("#backendStatus").innerHTML, /backend-status-chip direct/);
assert.match(elements.get("#backendStatus").innerHTML, /mp4\/mkv\/webm\/flv\/m3u8\/mpd/);
assert.match(elements.get("#backendStatus").innerHTML, /不录制 · 不绕过 DRM · 不刷课/);

elements.get("#llmProvider").value = "dashscope";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "https://dashscope.aliyuncs.com/compatible-mode/v1");
assert.equal(elements.get("#llmModel").value, "qwen-vl-max");
assert.equal(context.healthVisionProvider({}), "DashScope");
elements.get("#llmProvider").value = "siliconflow";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "https://api.siliconflow.cn/v1");
assert.equal(elements.get("#llmModel").value, "Qwen/Qwen2.5-VL-72B-Instruct");
assert.equal(context.healthVisionProvider({}), "SiliconFlow");
elements.get("#llmProvider").value = "local-openai";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "http://127.0.0.1:11434/v1");
assert.equal(elements.get("#llmModel").value, "qwen2.5vl:7b");
assert.equal(context.healthVisionProvider({}), "Local");
