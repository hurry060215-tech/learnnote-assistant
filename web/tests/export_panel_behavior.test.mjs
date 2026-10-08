import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

// Execute the real exports() body against a small in-memory DOM. No browser,
// network, or source-string assertions stand in for the state transitions.
const source = readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");
const exportPanel = source.slice(source.indexOf("  function exports() {"), source.indexOf("  async function annotations()"));
const defaults = {
  template: "print", include_note: true, include_annotations: true,
  include_source_link: true, include_timestamps: true, include_images: true,
  include_toc: false, include_transcript: false, include_practice: false,
  include_diagnostics: false, font_family: "Microsoft YaHei", font_size: 10.5,
  line_height: 1.6, paragraph_before: 0, paragraph_after: 7,
  margin_top: 18, margin_bottom: 18, margin_left: 18, margin_right: 18,
  orientation: "portrait",
};
const builtIns = [
  { id: "print", name: "打印 / Print", read_only: true, options: { ...defaults } },
  { id: "academic", name: "学术 / Academic", read_only: true, options: {
    ...defaults, template: "academic", font_size: 11, line_height: 1.8,
    margin_top: 25, margin_bottom: 25, margin_left: 25, margin_right: 25, include_toc: true,
  } },
  { id: "compact", name: "紧凑 / Compact", read_only: true, options: {
    ...defaults, template: "compact", font_size: 9.5, line_height: 1.25,
    paragraph_after: 4, margin_top: 12, margin_bottom: 12, margin_left: 12, margin_right: 12,
  } },
];
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
};
const flush = () => new Promise(resolve => setImmediate(resolve));

function createHarness({ presets = [], holdPreviews = false, holdPresets = false, kind = "task" } = {}) {
  const nodes = new Map(), calls = [], downloads = [], urls = [], previews = [], files = [];
  const pendingPresets = deferred();
  class Element {
    constructor(tag) {
      this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
      this.events = new Map(); this.checked = false; this.disabled = false;
      this.textContent = ""; this.open = false; this._value = undefined;
    }
    get value() {
      if (this.tagName === "SELECT") return this.options.find(option => option.value === this._value)?.value ?? this.options[0]?.value ?? "";
      return this._value ?? (this.tagName === "OPTION" ? this.textContent : "");
    }
    set value(value) { this._value = String(value); }
    get options() { return this.children.filter(child => child.tagName === "OPTION"); }
    get selectedOptions() { return this.options.filter(option => option.value === this.value).slice(0, 1); }
    append(...elements) { for (const element of elements) { element.parentElement = this; this.children.push(element); } }
    before(element) { element.parentElement = this.parentElement; this.parentElement.children.splice(this.parentElement.children.indexOf(this), 0, element); }
    after(element) { element.parentElement = this.parentElement; this.parentElement.children.splice(this.parentElement.children.indexOf(this) + 1, 0, element); }
    remove() { this.parentElement.children = this.parentElement.children.filter(child => child !== this); this.parentElement = null; }
    closest(selector) { return selector.startsWith(".") && (this.className || "").split(" ").includes(selector.slice(1)) ? this : this.parentElement?.closest(selector); }
    addEventListener(type, fn) { this.events.set(type, [...(this.events.get(type) || []), fn]); }
    async fire(type, { force = false } = {}) {
      if (type === "click" && this.disabled && !force) return;
      const event = { currentTarget: this, target: this };
      await Promise.all([this[`on${type}`], ...(this.events.get(type) || [])].filter(Boolean).map(fn => fn(event)));
    }
    click() { if (this.tagName === "A") downloads.push({ href: this.href, name: this.download }); else return this.fire("click"); }
    set innerHTML(html) {
      this.children = []; const stack = [this];
      for (const token of html.matchAll(/<\/?[^>]+>|[^<]+/g)) {
        const text = token[0];
        if (text.startsWith("</")) { stack.pop(); continue; }
        if (!text.startsWith("<")) { stack.at(-1).textContent += text; continue; }
        const tag = text.match(/^<([\w-]+)/)?.[1];
        if (!tag) continue;
        const element = new Element(tag);
        for (const attribute of text.slice(tag.length + 1, -1).matchAll(/([\w-]+)(?:="([^"]*)")?/g)) {
          const [, key, value = ""] = attribute;
          if (key === "id") { element.id = value; nodes.set(value, element); }
          else if (key === "class") element.className = value;
          else if (key === "checked" || key === "disabled") element[key] = true;
          else if (key === "value") element.value = value;
        }
        stack.at(-1).append(element);
        if (!["input", "br", "img", "hr"].includes(tag)) stack.push(element);
      }
    }
  }
  const document = { createElement: tag => new Element(tag), getElementById: id => nodes.get(id) };
  const dialog = new Element("dialog");
  const state = { selected: { id: "source-1", kind, title: "原始笔记" } };
  const api = async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : undefined;
    calls.push({ path, method: options.method || "GET", body });
    if (path === "/api/study/export-presets") return holdPresets ? pendingPresets.promise : { built_in_presets: builtIns, presets };
    if (path === "/api/study/export-fonts") return { fonts: [{ name: "Noto Serif SC", available: true }] };
    if (path.endsWith("/preview")) {
      if (!holdPreviews) return { html: "<p>Preview</p>", warnings: [] };
      const request = deferred(); previews.push(request); return request.promise;
    }
    if (options.method === "PUT") return { name: decodeURIComponent(path.split("/").at(-1)), options: body.options };
    if (options.method === "DELETE") return { deleted: true };
    throw new Error(`Unexpected request ${path}`);
  };
  const fetch = async (path, options) => {
    calls.push({ path, method: options.method, body: JSON.parse(options.body), download: true });
    const request = deferred(); files.push(request); return request.promise;
  };
  const context = vm.createContext({
    document, dialog, state, api, fetch,
    URL: { createObjectURL: () => { const url = `blob:${urls.length}`; urls.push(url); return url; }, revokeObjectURL() {} },
    setTimeout: fn => fn(),
  });
  vm.runInContext(`
    let generation = 0;
    const $ = id => document.getElementById(id);
    const current = () => ({ ...state.selected });
    const show = (_title, body) => { generation++; dialog.innerHTML = body; dialog.open = true; return generation; };
    ${exportPanel}
    globalThis.reopen = exports;
    globalThis.dismiss = () => { generation++; dialog.open = false; };
    exports();
  `, context);
  return { nodes, calls, downloads, urls, previews, files, state, dialog, pendingPresets, context,
    $: id => nodes.get(id), lastPreview: () => calls.filter(call => call.path.endsWith("/preview")).at(-1),
    fileResponse: (warnings = "", blob = async () => ({ type: "file" })) => ({ ok: true, headers: { get: name => name === "X-LearnNote-Export-Warning" ? warnings : null }, blob }),
  };
}

test("built-in templates are read-only, apply real layout, and carry template/diagnostics options", async () => {
  const h = createHarness({ presets: [{ name: "academic", options: { ...defaults, font_size: 18 } }] });
  await flush();
  const select = h.$("unifiedExportPreset");
  for (const name of ["print", "academic", "compact"]) assert.ok(select.options.some(option => option.value === `builtin:${name}`));
  assert.equal(h.$("exportDiagnostics").checked, false);
  assert.equal(h.lastPreview().body.options.include_diagnostics, false);
  select.value = "builtin:academic"; await select.fire("change");
  assert.equal(h.$("unifiedExportSize").value, "11");
  assert.equal(h.$("unifiedExportLeading").value, "1.8");
  for (const side of ["Top", "Bottom", "Left", "Right"]) assert.equal(h.$(`unifiedExport${side}`).value, "25");
  assert.equal(h.$("exportToc").checked, true);
  assert.equal(h.$("deleteUnifiedExportPreset").disabled, true);
  // Even direct dispatch to a disabled button cannot delete a built-in.
  await h.$("deleteUnifiedExportPreset").fire("click", { force: true });
  assert.equal(h.calls.filter(call => call.method === "DELETE").length, 0);
  h.$("exportDiagnostics").checked = true;
  await h.$("previewUnifiedExport").fire("click");
  assert.equal(h.lastPreview().body.options.template, "academic");
  assert.equal(h.lastPreview().body.options.include_diagnostics, true);
  select.value = "builtin:compact"; await select.fire("change");
  assert.equal(h.$("unifiedExportSize").value, "9.5");
  assert.equal(h.$("unifiedExportTop").value, "12");
  assert.equal(h.$("exportToc").checked, false);
  assert.equal(h.$("exportDiagnostics").checked, false);
  select.value = "user:academic"; await select.fire("change");
  assert.equal(h.$("unifiedExportSize").value, "18");
  assert.equal(h.$("deleteUnifiedExportPreset").disabled, false);
  await h.$("deleteUnifiedExportPreset").fire("click");
  assert.ok(!select.options.some(option => option.value === "user:academic"));
  assert.ok(select.options.some(option => option.value === "builtin:academic"));
});

test("saving a personal preset immediately inserts/selects it, preserves fonts, and can be deleted", async () => {
  const h = createHarness(); await flush();
  h.$("unifiedExportPreset").value = "builtin:academic";
  await h.$("unifiedExportPreset").fire("change");
  assert.equal(h.$("unifiedExportFont").value, "Microsoft YaHei");
  assert.ok(h.$("unifiedExportFont").options.some(option => option.value === "Noto Serif SC"));
  h.$("unifiedExportSize").value = "13";
  h.$("unifiedExportPresetName").value = "我的讲义";
  await h.$("saveUnifiedExportPreset").fire("click");
  assert.equal(h.$("unifiedExportPreset").value, "user:我的讲义");
  assert.equal(h.$("deleteUnifiedExportPreset").disabled, false);
  assert.equal(h.calls.find(call => call.method === "PUT").body.options.template, "academic");
  h.$("unifiedExportSize").value = "14";
  await h.$("saveUnifiedExportPreset").fire("click");
  assert.equal(h.$("unifiedExportPreset").options.filter(option => option.value === "user:我的讲义").length, 1);
  await h.$("deleteUnifiedExportPreset").fire("click");
  assert.ok(!h.$("unifiedExportPreset").options.some(option => option.value === "user:我的讲义"));
  assert.equal(h.$("deleteUnifiedExportPreset").disabled, true);
});

test("late initial preset loading cannot overwrite a preset saved during the request", async () => {
  const h = createHarness({ holdPresets: true }); await flush();
  h.$("unifiedExportPresetName").value = "My preset";
  h.$("unifiedExportSize").value = "15";
  await h.$("saveUnifiedExportPreset").fire("click");
  h.pendingPresets.resolve({ built_in_presets: builtIns, presets: [{ name: "My preset", options: { ...defaults, font_size: 8 } }] });
  await flush();
  assert.equal(h.$("unifiedExportPreset").value, "user:My preset");
  await h.$("unifiedExportPreset").fire("change");
  assert.equal(h.$("unifiedExportSize").value, "15");
});

test("download warnings explain PDF emoji fallback, Word TOC, formulas, and missing fonts", async () => {
  const h = createHarness(); await flush();
  h.$("unifiedExportFormat").value = "pdf";
  const work = h.$("downloadUnifiedExport").fire("click");
  const codes = ["non_bmp_symbols_rendered_as_unicode_names", "docx_toc_page_numbers_require_field_update", "unrecognized_math_commands_preserved_as_source", "requested_pdf_font_unavailable_using_cjk_fallback"];
  h.files[0].resolve(h.fileResponse(codes.join(","))); await work;
  assert.equal(h.downloads.length, 1);
  assert.equal(h.downloads[0].name, "原始笔记.pdf");
  const status = h.$("unifiedExportStatus").textContent;
  for (const text of ["可读名称", "更新域", "公式命令已保留原文", "中文替代字体"]) assert.ok(status.includes(text), status);
  for (const code of codes) assert.ok(!status.includes(code));
  assert.equal(h.$("downloadUnifiedExport").disabled, false);
});

test("latest preview wins even when older responses and errors arrive later", async () => {
  const h = createHarness({ holdPreviews: true }); await flush();
  const second = h.$("previewUnifiedExport").fire("click");
  h.previews[1].resolve({ html: "new preview", warnings: [] }); await second;
  h.previews[0].resolve({ html: "old preview", warnings: ["old warning"] }); await flush();
  assert.equal(h.$("unifiedExportPreview").srcdoc, "new preview");
  assert.ok(!h.$("unifiedExportStatus").textContent.includes("old warning"));
  const third = h.$("previewUnifiedExport").fire("click");
  const fourth = h.$("previewUnifiedExport").fire("click");
  h.previews[3].resolve({ html: "newest preview", warnings: [] }); await fourth;
  h.previews[2].reject(new Error("late error")); await third;
  assert.equal(h.$("unifiedExportPreview").srcdoc, "newest preview");
  assert.ok(!h.$("unifiedExportStatus").textContent.includes("late error"));
});

test("duplicate in-flight download clicks submit once and failed downloads can retry", async () => {
  const h = createHarness(); await flush();
  const button = h.$("downloadUnifiedExport");
  const first = button.fire("click");
  await button.fire("click", { force: true });
  assert.equal(h.files.length, 1);
  assert.equal(button.disabled, true);
  h.files[0].reject(new Error("connection lost")); await first;
  assert.equal(button.disabled, false);
  const retry = button.fire("click");
  h.files[1].resolve(h.fileResponse()); await retry;
  assert.equal(h.downloads.length, 1);
});

for (const interruption of ["dismiss", "source change", "source kind change", "reopen"]) {
  test(`${interruption} prevents a late download and preview from affecting the new view`, async () => {
    const h = createHarness({ holdPreviews: true }); await flush();
    const oldFrame = h.$("unifiedExportPreview"), oldStatus = h.$("unifiedExportStatus");
    const work = h.$("downloadUnifiedExport").fire("click");
    if (interruption === "dismiss") h.context.dismiss();
    else if (interruption === "source change") h.state.selected = { ...h.state.selected, id: "source-2" };
    else if (interruption === "source kind change") h.state.selected = { ...h.state.selected, kind: "material" };
    else { h.context.dismiss(); h.context.reopen(); }
    h.files[0].resolve(h.fileResponse());
    h.previews[0].resolve({ html: "late preview", warnings: [] });
    await work; await flush();
    assert.equal(h.downloads.length, 0);
    assert.equal(h.urls.length, 0);
    assert.notEqual(oldFrame.srcdoc, "late preview");
    assert.notEqual(oldStatus.textContent, "文件已生成。");
    if (interruption === "reopen") assert.notEqual(h.$("unifiedExportPreview").srcdoc, "late preview");
  });
}

test("dismissal while the response body is loading still suppresses the download", async () => {
  const h = createHarness({ kind: "material" }); await flush();
  const blob = deferred();
  const work = h.$("downloadUnifiedExport").fire("click");
  h.files[0].resolve(h.fileResponse("", () => blob.promise)); await flush();
  h.dialog.open = false;
  blob.resolve({ type: "file" }); await work;
  assert.equal(h.downloads.length, 0);
  assert.equal(h.urls.length, 0);
  assert.ok(h.calls.some(call => call.path === "/api/library/materials/source-1/exports/html"));
});
