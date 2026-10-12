import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const settings = fs.readFileSync(path.join(root, "web", "desk-settings.js"), "utf8");
const css = fs.readFileSync(path.join(root, "web", "desk.css"), "utf8");
const tools = fs.readFileSync(path.join(root, "web", "desk-tools.js"), "utf8");
const graph = fs.readFileSync(path.join(root, "web", "course-graph-snapshot.js"), "utf8");
const desk = fs.readFileSync(path.join(root, "web", "desk.js"), "utf8");
const batch = fs.readFileSync(path.join(root, "web", "material-batch.js"), "utf8");

test("settings exposes the explainable local-first model route", () => {
  assert.match(settings, /model-route-panel/);
  assert.match(settings, /\/api\/model\/route/);
  assert.match(settings, /item.network === "required"/);
  assert.match(settings, /blocking_reasons/);
  assert.match(css, /\.model-route-list/);
});

test("pre-submit text, vision and no-key subtitle routes disclose the selected data without probes", () => {
  for (const newline of ["\n", "\r\n"]) {
    const script = desk.replace(/\r?\n/g, newline);
    const body = script.slice(script.indexOf("function updateContentMode()"), script.indexOf('for (const choice of document.querySelectorAll'));
    const selected = { mode: "text" }, elements = new Map();
    const element = id => {
      if (!elements.has(id)) elements.set(id, { textContent: "", closest: () => ({ hidden: false }) });
      return elements.get(id);
    };
    const state = { input: "url", processing: {}, model: {
      base_url: "https://viewer:fixture-password@models.invalid/v1?token=fixture-query#fragment",
      model: "synthetic-model", use_saved_connection: false,
    }, key: "", health: {} };
    const context = vm.createContext({ URL, state, $: element, document: { querySelector: () => ({ value: selected.mode }) } });
    vm.runInContext(batch.replaceAll("export ", "") + "\n" + body, context);
    for (const transcriber of ["faster-whisper", "openai-compatible", "groq"]) {
      state.processing.transcriber = transcriber;
      for (const mode of ["text", "visual", "subtitles"]) {
        selected.mode = mode;
        context.updateContentMode();
        const disclosure = element("contentModeExplanation").textContent;
        assert.doesNotMatch(disclosure, /fixture-password|fixture-query|fragment|viewer|\/v1/);
        if (mode === "subtitles") {
          assert.match(disclosure, /不调用转写或总结模型.*没有字幕时停止/);
          assert.doesNotMatch(disclosure, /将音频发送|将交给/);
        } else {
          assert.match(disclosure, /字幕.*整理要求.*models\.invalid.*synthetic-model/);
          assert.match(disclosure, /无 Key.*仅提取字幕/);
          assert.match(disclosure, /费用与耗时区间未知.*测量依据/);
          assert.match(disclosure, /上下文和图片上限未知/);
          assert.equal(disclosure.includes("选定画面"), mode === "visual");
          assert.equal(disclosure.includes("将音频发送"), transcriber !== "faster-whisper");
        }
      }
    }
  }
});

test("route settings render capability uncertainty and ignore late old responses", async () => {
  for (const newline of ["\n", "\r\n"]) {
    const script = settings.replace(/\r?\n/g, newline), pending = [], elements = new Map();
    const element = id => {
      if (!elements.has(id)) elements.set(id, { textContent: "", innerHTML: "", value: "", replaceChildren() { this.innerHTML = ""; } });
      return elements.get(id);
    };
    const context = vm.createContext({ URLSearchParams, $: element, pref: {}, esc: value => String(value),
      api: url => new Promise((resolve, reject) => pending.push({ url, resolve, reject })) });
    vm.runInContext(script.slice(script.indexOf("  let routeRequest = 0;"), script.indexOf('  $("refreshModelRoute").onclick')), context);
    const old = context.loadModelRoute(), recent = context.loadModelRoute();
    const route = { routes: [], blocking_reasons: [], offline_source_confirmed: false,
      capability_catalog: Object.fromEntries(["text", "vision", "asr", "context_limit", "image_limit"].map(key => [key, { detail: key + ": unknown" }])),
      local_fallback: { detail: "无 Key 时可提取字幕" }, estimates: { detail: "费用与耗时区间未知：未测量" } };
    pending[1].resolve(route); await recent;
    const rendered = element("modelRouteSummary").textContent;
    assert.match(rendered, /未调用模型或下载权重/);
    assert.match(rendered, /无 Key/);
    assert.match(element("modelRouteCapabilities").textContent, /text: unknown.*vision: unknown.*asr: unknown.*context_limit: unknown.*image_limit: unknown/);
    assert.equal(element("modelRouteEstimates").textContent, route.estimates.detail);
    pending[0].reject(new Error("Old request failed")); await old;
    assert.equal(element("modelRouteSummary").textContent, rendered);
    const retry = context.loadModelRoute(); pending[2].resolve(route); await retry;
    assert.equal(element("modelRouteSummary").textContent, rendered);
    assert(pending.every(item => item.url.startsWith("/api/model/route?")), "Rendering readiness only uses the local report API");
  }
});

test("course comparison keeps a visual relationship view and an evidence list", () => {
  assert.match(tools, /function relationshipGraph\(result\)/);
  assert.match(tools, /relationshipGraph as snapshotRelationshipGraph/);
  assert.match(graph, /relationship-graph/);
  assert.match(tools, /evidence_ids/);
  assert.match(tools, /关系列表/);
});
