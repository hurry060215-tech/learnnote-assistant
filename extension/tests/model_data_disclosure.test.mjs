import assert from "node:assert/strict";
import test from "node:test";
import { createSidepanelHarness, videoContext } from "./sidepanel_test_harness.mjs";

for (const locale of ["zh-CN", "en"]) {
  test(`sidepanel ${locale} shows source metadata and separate page scopes before sending`, async () => {
    const h = await createSidepanelHarness({ locale, contexts: [videoContext()], health: {
      service: "learnnote", app_version: "fixture", backend_version: "fixture", protocol_version: 1,
      llm_model_configured: true, default_llm_base_url: "https://viewer:secret@models.invalid/v1?token=hidden",
      default_llm_model: "synthetic-model",
    } });
    await h.api.checkClient(); await h.api.collectContext(true); h.api.setProcessingMode("study", false);
    const text = h.elements.get("#modeDescription").textContent;
    assert.match(text, /models\.invalid.*synthetic-model/);
    assert.match(text, locale === "en" ? /source title, page URL/i : /来源标题、页面链接/);
    assert.match(text, /4,000/);
    assert.match(text, locale === "en" ? /full-page fallback separately/i : /页面全文兜底.*分开审阅/);
    assert.doesNotMatch(text, /viewer|secret|token=hidden/);
    assert.equal(h.sentMessages.some(message => message.type === "start-current-task"), false);
    h.api.setProcessingMode("quick", false);
    assert.doesNotMatch(h.elements.get("#modeDescription").textContent, /models\.invalid|synthetic-model/);
  });
}
