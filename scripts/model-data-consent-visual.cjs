// Bounded addition to the existing offline Windows Edge route fixture.
const assert = require("node:assert/strict");
const path = require("node:path");

module.exports = async function checkModelDataConsent(page, output, report) {
  await page.locator("#settingsDialog [data-close]").first().click();
  const open = async () => page.evaluate(async () => {
    const { reviewTaskModelData } = await import("/web/model-data-consent.js?v=20261016");
    window.consentOutcome = "pending";
    reviewTaskModelData({ task: { id: "synthetic-consent", model_data_preview: {
      fingerprint: "synthetic-reviewed-source", mode: "video", title: "Synthetic course title <img src=x>",
      source_url: "https://source.invalid/lesson?p=2", context_available: true,
      context_excerpt: "Synthetic chapter outline. Only this reviewed excerpt is optional context.",
      fallback_available: true, captured_page_text: "Synthetic full-page source text, kept locally until separately approved.",
      captured_subtitles: "Synthetic browser subtitle cue.", page_text_limit: 50000, subtitle_text_limit: 10000,
    } }, options: { content_mode: "visual", visual_understanding: true, transcriber: "groq",
      llm_base_url: "https://viewer:synthetic-secret@models.invalid/v1?token=synthetic-query", llm_model: "synthetic-model" },
    }).then(value => { window.consentOutcome = value; });
  });
  const dialog = page.locator('dialog[aria-labelledby="modelDataConsentTitle"]');
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const theme of ["light", "dark"]) {
      await page.evaluate(dark => document.body.classList.toggle("dark", dark), theme === "dark");
      await open(); await dialog.waitFor();
      const text = await dialog.innerText();
      assert.match(text, /models\.invalid.*synthetic-model/);
      assert.match(text, /来源标题.*Synthetic course title/);
      assert.match(text, /来源页面链接.*source\.invalid/);
      assert.match(text, /没有可验证字幕.*音频.*models\.invalid/);
      assert.doesNotMatch(text, /synthetic-secret|synthetic-query/);
      assert.equal(await dialog.locator("img").count(), 0, "Source title must be inert text");
      assert.equal(await page.locator("#allowModelPageContext").isChecked(), false);
      assert.equal(await page.locator("#allowPageTextFallback").isChecked(), false);
      assert.equal(await dialog.getByRole("button", { name: "同意并开始" }).isEnabled(), false);
      await dialog.locator("summary").first().click();
      assert.match(await dialog.innerText(), /Only this reviewed excerpt/);
      assert(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth + 1), "Consent must wrap at narrow widths");
      const file = `consent-${width}-${theme}.png`;
      await page.screenshot({ path: path.join(output, file), fullPage: true }); report.screenshots.push(file);
      await dialog.getByRole("button", { name: "取消", exact: true }).click();
      await page.waitForFunction(() => window.consentOutcome === null);
    }
  }
  await open(); await page.locator("#allowModelPageContext").check();
  await page.locator("#modelDataConsent").check();
  await dialog.getByRole("button", { name: "同意并开始" }).click();
  await page.waitForFunction(() => window.consentOutcome !== "pending");
  assert.deepEqual(await page.evaluate(() => window.consentOutcome), {
    allow_model_page_context: true, allow_page_text_fallback: false, review_fingerprint: "synthetic-reviewed-source",
  });
  await open();
  assert.equal(await page.locator("#allowModelPageContext").isChecked(), false, "No remembered context approval");
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => window.consentOutcome === null);
  report.taskDataConsent = { preview_and_cancel_send_nothing: true, independent_scopes: true, fresh_each_time: true };
};
