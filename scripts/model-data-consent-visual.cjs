// Bounded addition to the existing offline Windows Edge route fixture.
const assert = require("node:assert/strict");
const path = require("node:path");
const BACKGROUND_CONTROL_SELECTOR = "#homeLocal";

function nativeModalFocusIsSafe(state) {
  const inModal = state.insideModal === true && state.rootFallback === false;
  const browserControls = state.insideModal === false && state.documentHasFocus === false
    && state.rootFallback === true && ["BODY", "HTML"].includes(state.activeTag);
  return state.open === true && state.modal === true && state.openDialogs === 1
    && state.outcomePending === true && state.backgroundVisible === true && state.backgroundDisabled === false
    && state.backgroundFocusRefused === true && (inModal || browserControls);
}

module.exports = async function checkModelDataConsent(page, output, report) {
  await page.locator("#settingsDialog [data-close]").first().click();
  const open = async () => page.evaluate(async () => {
    const { reviewTaskModelData } = await import("/web/model-data-consent.js?v=initial-focus-20261016");
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
  report.taskDataConsentFocus = [];
  const focusBackground = async () => {
    const background = page.locator(BACKGROUND_CONTROL_SELECTOR);
    await background.waitFor({ state: "visible" });
    await page.waitForFunction(selector => {
      const node = document.querySelector(selector);
      return node && !node.matches(":disabled");
    }, BACKGROUND_CONTROL_SELECTOR);
    await background.scrollIntoViewIfNeeded();
    assert(await background.evaluate(node => {
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.left >= 0
        && rect.bottom <= innerHeight && rect.right <= innerWidth;
    }), "Hydrated home opener must be visible inside the viewport before focus");
    await background.focus();
    assert.equal(await page.evaluate(() => document.activeElement?.id), "homeLocal", "Visible opener must receive focus");
  };
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const theme of ["light", "dark"]) {
      await page.evaluate(dark => document.body.classList.toggle("dark", dark), theme === "dark");
      await focusBackground();
      await open(); await dialog.waitFor();
      assert(await dialog.evaluate(node => {
        const bounds = node.getBoundingClientRect();
        const topFields = [node.querySelector("h2"), ...node.querySelectorAll("section > p")].slice(0, 4);
        return node.scrollTop <= 1 && document.activeElement === node.querySelector("h2")
          && topFields.every(item => { const rect = item.getBoundingClientRect();
            return rect.top >= bounds.top && rect.bottom <= bounds.bottom; });
      }), "Initial focus and recipient/title/URL must be visible at the top");
      if (width === 390) {
        const initial = `consent-${width}-${theme}-initial.png`;
        await page.screenshot({ path: path.join(output, initial), fullPage: true }); report.screenshots.push(initial);
      }
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
      if (width === 390) {
        await dialog.evaluate(node => { node.scrollTop = node.scrollHeight; });
        assert(await dialog.evaluate(node => {
          const bounds = node.getBoundingClientRect();
          return node.scrollTop > 0 && node.scrollWidth <= node.clientWidth + 1
            && [...node.querySelectorAll("footer button")].every(item => {
              const rect = item.getBoundingClientRect();
              return rect.top >= bounds.top && rect.bottom <= bounds.bottom; });
        }), "Mobile dialog must scroll to reachable bottom actions without overflow");
        const bottom = `consent-${width}-${theme}-bottom.png`;
        await page.screenshot({ path: path.join(output, bottom), fullPage: true }); report.screenshots.push(bottom);
      }
      await dialog.getByRole("button", { name: "取消", exact: true }).focus();
      // Native Tab may visit browser chrome. The app behind a modal must
      // remain inert; do not replace native browser navigation with a trap.
      // https://html.spec.whatwg.org/multipage/interaction.html#sequential-focus-navigation
      let browserExcursion = false;
      for (const key of ["Tab", "Shift+Tab"]) {
        await page.keyboard.press(key);
        const focus = await dialog.evaluate((node, selector) => {
          const active = document.activeElement, background = document.querySelector(selector);
          const rect = background.getBoundingClientRect();
          const state = { activeTag: active?.tagName, activeId: active?.id || "", documentHasFocus: document.hasFocus(),
            insideModal: node.contains(active), rootFallback: active === document.body || active === document.documentElement,
            open: node.open, modal: node.matches(":modal"), openDialogs: document.querySelectorAll("dialog[open]").length,
            backgroundVisible: rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.left >= 0
              && rect.bottom <= innerHeight && rect.right <= innerWidth, backgroundDisabled: background.disabled,
            outcomePending: window.consentOutcome === "pending" };
          background.focus({ preventScroll: true });
          state.backgroundFocusRefused = document.activeElement !== background;
          return state;
        }, BACKGROUND_CONTROL_SELECTOR);
        report.taskDataConsentFocus.push({ width, theme, key, ...focus });
        assert(nativeModalFocusIsSafe(focus),
          `Native modal must retain focus or permit only browser controls with inert background: ${JSON.stringify(focus)}`);
        if (browserExcursion) assert(focus.insideModal && focus.documentHasFocus,
          `Reverse Tab must return from browser controls to the modal: ${JSON.stringify(focus)}`);
        browserExcursion = !focus.insideModal && !focus.documentHasFocus && focus.rootFallback;
        assert.equal(await page.locator("#modelDataConsent").isChecked(), false);
      }
      await dialog.getByRole("button", { name: "取消", exact: true }).click();
      await page.waitForFunction(() => window.consentOutcome === null);
      assert.equal(await page.evaluate(() => document.activeElement?.id), "homeLocal", "Cancel restores opener focus");
    }
  }
  await open(); await page.locator("#allowModelPageContext").check();
  await page.locator("#modelDataConsent").check();
  await dialog.getByRole("button", { name: "同意并开始" }).click();
  await page.waitForFunction(() => window.consentOutcome !== "pending");
  assert.deepEqual(await page.evaluate(() => window.consentOutcome), {
    allow_model_page_context: true, allow_page_text_fallback: false, review_fingerprint: "synthetic-reviewed-source",
  });
  await focusBackground(); await open();
  assert.equal(await page.locator("#allowModelPageContext").isChecked(), false, "No remembered context approval");
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => window.consentOutcome === null);
  assert.equal(await page.evaluate(() => document.activeElement?.id), "homeLocal", "Escape restores opener focus");
  report.taskDataConsent = { preview_and_cancel_send_nothing: true, independent_scopes: true, fresh_each_time: true,
    initial_metadata_visible: true, mobile_bottom_actions_reachable: true, keyboard_focus_restored: true, native_background_inert: true };
};

module.exports.nativeModalFocusIsSafe = nativeModalFocusIsSafe;
module.exports.BACKGROUND_CONTROL_SELECTOR = BACKGROUND_CONTROL_SELECTOR;
