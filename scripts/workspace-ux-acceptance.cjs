// Settings and assistant editing regressions. Uses mocked preference/model-free APIs.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");

(async () => {
  const base = process.argv[2] || "http://127.0.0.1:18920";
  const out =
    process.argv[3] ||
    fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-settings-"));
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const p = await browser.newPage({
    viewport: { width: 1440, height: 960 },
    reducedMotion: "reduce",
  });
  const errors = [];
  p.on("pageerror", (error) => errors.push(error.message));
  let persisted = (
    await (await p.request.get(base + "/api/preferences")).json()
  ).task_options;
  let writes = 0,
    failWrite = false,
    delayRead = false,
    releaseRead;
  await p.route("**/api/preferences", async (route) => {
    if (route.request().method() === "PUT") {
      writes++;
      if (failWrite)
        return route.fulfill({
          status: 503,
          json: { detail: "验收：本机服务暂不可用" },
        });
      persisted = route.request().postDataJSON().task_options;
    } else if (delayRead)
      await new Promise((resolve) => {
        releaseRead = resolve;
      });
    return route.fulfill({ json: { task_options: persisted } });
  });
  const section = (key) =>
    p.locator(`[data-settings-section="${key}"]`).click();
  const status = () => p.locator("#preferencesStatus").innerText();
  async function waitUntil(predicate) {
    const deadline = Date.now() + 10000;
    while (!predicate()) {
      assert(Date.now() < deadline, "expected request did not start within 10 seconds");
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
  }
  async function closeClean() {
    await p.locator("#settingsDialog [data-close]").click();
    await p.waitForSelector("#settingsDialog", { state: "hidden" });
  }
  try {
    await p.goto(base);
    assert.match(await p.title(), /LearnNote/);
    await p.waitForFunction(() => !!window.LearnNoteSettings);
    assert.match(await p.locator("body").innerText(), /新建笔记/);
    await p.locator("#settings").click();
    await section("processing");
    await p.locator("#prefInterval").fill("0");
    await section("appearance");
    await p.locator("#prefReaderSize").selectOption("20");
    await p.locator("#prefFont").selectOption("serif");
    assert.equal(
      await p.evaluate(() =>
        getComputedStyle(document.documentElement)
          .getPropertyValue("--reader-size")
          .trim(),
      ),
      "20px",
    );
    failWrite = true;
    await p.locator("#savePreferences").click();
    assert.match(await status(), /阅读与外观已保存/);
    assert.equal(
      writes,
      0,
      "appearance must not call backend or validate hidden fields",
    );
    assert.match(await status(), /其他分类/);
    p.once("dialog", (dialog) => dialog.dismiss());
    await p.keyboard.press("Escape");
    assert(await p.locator("#settingsDialog").isVisible());
    await section("processing");
    await p.locator("#prefInterval").fill(String(persisted.frame_interval));
    await closeClean();
    await p.reload();
    await p.locator("#settings").click();
    await section("appearance");
    assert.equal(await p.locator("#prefReaderSize").inputValue(), "20");
    assert.equal(await p.locator("#prefFont").inputValue(), "serif");
    await p.locator("#prefReaderSize").selectOption("15");
    p.once("dialog", (dialog) => dialog.accept());
    await p.keyboard.press("Escape");
    await p.waitForFunction(() => !document.getElementById("settingsDialog").open && getComputedStyle(document.documentElement).getPropertyValue("--reader-size").trim() === "20px");
    assert.equal(
      await p.evaluate(() =>
        getComputedStyle(document.documentElement)
          .getPropertyValue("--reader-size")
          .trim(),
      ),
      "20px",
      "discarding preview restores saved appearance",
    );

    // A late preference response must not reset an edit started after opening.
    delayRead = true;
    await p.locator("#settings").click();
    await section("notes");
    await p.locator("#prefCustom").fill("保留我正在编辑的要求");
    await p.waitForFunction(
      () =>
        document.querySelector("#settingsDialog").dataset.unsaved === "true",
    );
    await waitUntil(() => releaseRead);
    releaseRead();
    delayRead = false;
    await p.waitForTimeout(100);
    assert.equal(
      await p.locator("#prefCustom").inputValue(),
      "保留我正在编辑的要求",
    );
    await p.locator("#savePreferences").click();
    await p.waitForFunction(() =>
      document
        .querySelector("#preferencesStatus")
        .textContent.includes("未能保存"),
    );
    assert.equal(
      await p.locator("#prefCustom").inputValue(),
      "保留我正在编辑的要求",
    );
    failWrite = false;
    await section("appearance");
    await p.locator("#prefAccent").selectOption("blue");
    await section("notes");
    await p.locator("#savePreferences").click();
    await p.waitForFunction(() =>
      document
        .querySelector("#preferencesStatus")
        .textContent.includes("处理设置已保存"),
    );
    assert.equal(persisted.note_profile_prompt, "保留我正在编辑的要求");
    assert.match(await status(), /其他分类/);
    await section("model");
    await p.locator("#model").fill("ux-test-model");
    await p.locator("#savePreferences").click();
    assert(
      await p.locator("#settingsDialog").isVisible(),
      "model save must not discard other sections",
    );
    assert.match(await status(), /模型连接已保存.*其他分类/);
    await section("appearance");
    await p.locator("#savePreferences").click();
    await closeClean();
    await p.locator("#theme").click();
    assert.equal(
      await p.evaluate(() =>
        getComputedStyle(document.body).getPropertyValue("--accent").trim(),
      ),
      "#abbdff",
      "selected accent remains meaningful in dark mode",
    );
    await p.locator("#theme").click();
    await p.locator("#settings").click();
    await section("notes");
    await p.locator("#prefStyle").selectOption("concise");
    await p.locator("#prefStyle").press("Enter");
    // Select Enter opens its menu, so use a text field to exercise form submission.
    await p
      .locator("#prefCustom")
      .evaluate((element) => element.form.requestSubmit());
    await p.waitForFunction(() =>
      document
        .querySelector("#preferencesStatus")
        .textContent.includes("处理设置已保存"),
    );
    assert.equal(persisted.note_style, "concise");
    assert(await p.locator("#settingsDialog").isVisible());
    await closeClean();

    // Closing the assistant cannot make its pending request disappear or erase a new draft.
    let releaseAnswer;
    await p.route("**/api/assistant/execute", async (route) => {
      await new Promise((resolve) => {
        releaseAnswer = resolve;
      });
      await route.fulfill({
        json: {
          answer: "这是本地验收回答。",
          source: "local",
          skill: { id: "product.help", name: "使用帮助", scope: "product" },
          execution: { state: "completed" },
        },
      });
    });
    await p.locator("#aiAssistant").click();
    await p.waitForSelector('#assistantSkill option[value="product.help"]', {
      state: "attached",
    });
    await p.locator("#assistantSkill").selectOption("product.help");
    await p.locator("#aiQuestion").fill("怎么导出？");
    await p.locator("#aiSend").click();
    await waitUntil(() => releaseAnswer);
    await p.locator("#aiQuestion").focus();
    await p.keyboard.press("Escape");
    assert.equal(
      await p.evaluate(() => document.activeElement.id),
      "aiAssistant",
    );
    await p.locator("#aiAssistant").click();
    assert(await p.locator("#aiSend").isDisabled());
    await p.locator("#aiQuestion").fill("这是下一条未发送的问题");
    releaseAnswer();
    await p.waitForFunction(() => !document.querySelector("#aiSend").disabled);
    assert.equal(
      await p.locator("#aiQuestion").inputValue(),
      "这是下一条未发送的问题",
    );
    assert.match(
      await p.locator(".assistant-answer").last().innerText(),
      /本地验收回答/,
    );
    await p.locator("#closeAssistant").click();

    await p.locator("#settings").click();
    await section("appearance");
    await p.screenshot({
      path: path.join(out, "appearance-desktop.png"),
      animations: "disabled",
    });
    await p.setViewportSize({ width: 390, height: 844 });
    await section("appearance");
    assert(await p.locator("#savePreferences").isVisible());
    assert.equal(
      await p.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      true,
    );
    await p.screenshot({
      path: path.join(out, "appearance-mobile.png"),
      animations: "disabled",
    });
    assert.deepEqual(errors, []);
    console.log(
      JSON.stringify(
        {
          ok: true,
          base,
          viewports: ["1440x960", "390x844"],
          preference_writes: writes,
          browser: "Browser plugin not available; Playwright Edge",
          checks: [
            "offline appearance save",
            "discard live preview",
            "per-section dirty state",
            "late response preserves edits",
            "failed save preserves edits",
            "model save preserves other sections",
            "section form submit",
            "assistant pending continuity",
            "new draft preserved",
            "no page errors",
          ],
          out,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
