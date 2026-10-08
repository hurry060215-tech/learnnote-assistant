import assert from "node:assert/strict";
import vm from "node:vm";
import { readFile } from "node:fs/promises";
import { createSidepanelHarness, videoContext } from "./sidepanel_test_harness.mjs";

const source = await readFile(new URL("../i18n.js", import.meta.url), "utf8");
const english = JSON.parse(await readFile(new URL("../_locales/en/messages.json", import.meta.url), "utf8"));
const chinese = JSON.parse(await readFile(new URL("../_locales/zh_CN/messages.json", import.meta.url), "utf8"));
function runtime(locale, getMessage = () => "") {
  const context = { chrome: { i18n: { getUILanguage: () => locale, getMessage } } };
  vm.createContext(context);
  vm.runInContext(source, context);
  return context.LearnNoteI18n;
}
for (const [locale, catalog] of [["en-US", english], ["zh-CN", chinese], ["fr-FR", chinese]]) {
  const api = runtime(locale);
  for (const [key, value] of Object.entries(catalog)) assert.equal(api.message(key), value.message, `${locale}: ${key} fallback`);
}
assert.equal(runtime("en-GB", () => { throw Error("API unavailable"); }).message("openClient"), "Open workspace");
const withoutChrome = {};
vm.createContext(withoutChrome); vm.runInContext(source, withoutChrome);
assert.equal(withoutChrome.LearnNoteI18n.message("openClient"), "打开工作台");
assert.equal(runtime("en").message("not_a_resource"), "not_a_resource");
assert.equal(runtime("en").message("model_no_images", { model: "用户模型 {model} <img>" }), "Model 用户模型 {model} <img> does not support images. Choose a vision model or a text note.");
assert.equal(runtime("en").productMessage("当前站点权限已撤销，本次任务未创建。"), "Site permission was revoked. No task was created.");
assert.equal(runtime("en").productMessage("未知服务详情 <script>"), "未知服务详情 <script>", "unknown diagnostics retain the original wording");

const makeNode = (dataset, textContent = "", value = "") => ({ dataset, textContent, value, attrs: {}, setAttribute(key, value) { this.attrs[key] = value; } });
const label = makeNode({ i18n: "sendToClient" });
const aria = makeNode({ i18nAria: "refreshLabel" });
const title = makeNode({ i18nTitle: "refreshTitle" });
const placeholder = makeNode({ i18nPlaceholder: "ui_ask_a_question_about_this_video" }, "", "用户问题 {model}");
const userContent = makeNode({}, "当前站点权限已撤销，本次任务未创建。");
const root = { documentElement: makeNode({}), querySelectorAll: selector => ({
  "[data-i18n]": [label], "[data-i18n-aria]": [aria], "[data-i18n-title]": [title], "[data-i18n-placeholder]": [placeholder]
})[selector] || [] };
runtime("en").apply(root);
assert.equal(label.textContent, "Send to client");
assert.equal(aria.attrs["aria-label"], english.refreshLabel.message);
assert.equal(title.attrs.title, english.refreshTitle.message);
assert.equal(placeholder.attrs.placeholder, "Ask a question about this video…");
assert.equal(placeholder.value, "用户问题 {model}");
assert.equal(userContent.textContent, "当前站点权限已撤销，本次任务未创建。");
assert.equal(root.documentElement.attrs.lang, "en");
runtime("zh-CN").apply(root);
assert.equal(label.textContent, "发送到客户端");
assert.equal(root.documentElement.attrs.lang, "zh-CN");

const titleText = "正在连接客户端";
const page = videoContext({ title: titleText });
const panel = await createSidepanelHarness({ locale: "en-US", contexts: [page], missingMessages: ["ui_local_workspace_connected"] });
assert.equal(panel.elements.get("#connectionTitle").textContent, "Local workspace connected");
assert.equal(panel.elements.get("#videoTitle").textContent, titleText, "a title matching UI copy is still user content");
assert.equal(panel.elements.get("#sendButtonLabel").textContent, "Generate text note");
assert.match(panel.elements.get("#modeDescription").textContent, /No image analysis/);
panel.api.setProcessingMode("quick");
assert.equal(panel.elements.get("#sendButtonLabel").textContent, "Extract transcript");
assert.match(panel.elements.get("#modeDescription").textContent, /No video download/);
panel.api.setProcessingMode("deep");
assert.equal(panel.elements.get("#sendButtonLabel").textContent, "Generate visual note");
assert.match(panel.elements.get("#modeDescription").textContent, /vision model/);
assert.match(panel.api.renderQuickMarkdown("# 当前站点权限已撤销，本次任务未创建。\n\n字幕 <img> {model}"), /<h1>当前站点权限已撤销，本次任务未创建。<\/h1>/);
assert.match(panel.api.subtitleSrt([{ start: 0, end: 2, text: "用户字幕 {model}" }]), /用户字幕 \{model\}/);

const incompatible = await createSidepanelHarness({ locale: "en", contexts: [page], health: { service: "learnnote", app_version: "0.1", backend_version: "0.1", protocol_version: 3 } });
assert.equal(incompatible.elements.get("#connectionTitle").textContent, "Extension and workbench are incompatible");
assert.match(incompatible.elements.get("#connectionDetail").textContent, /protocol 1.*protocol 3/);
const offline = await createSidepanelHarness({ locale: "en", contexts: [page], health: Error("offline") });
assert.equal(offline.elements.get("#connectionTitle").textContent, "Local workspace is not running");
const failure = await createSidepanelHarness({ locale: "en", contexts: [page], start: { error: "当前站点权限已撤销，本次任务未创建。" } });
assert.equal(await failure.api.sendToClient(), false);
assert.equal(failure.elements.get("#handoffStatus").textContent, "Site permission was revoked. No task was created.");
const denial = await createSidepanelHarness({ locale: "en", contexts: [page], permissions: { granted: false, requestResult: false } });
assert.equal(await denial.api.sendToClient(), false);
assert.match(denial.elements.get("#handoffStatus").textContent, /No task was created/);
assert.equal(denial.sentMessages.some(item => item.type === "start-current-task"), false);
console.log("English/Chinese static, dynamic, errors, ARIA, fallback and original-content localization boundaries passed");
