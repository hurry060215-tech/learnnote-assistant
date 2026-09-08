const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("fs");
(async () => {
  const base = process.argv[2] || "http://127.0.0.1:18790",
    out = process.argv[3] || "build/global-ui";
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const p = await browser.newPage({
    viewport: { width: 1440, height: 960 },
    reducedMotion: "reduce",
  });
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  async function send(text, skill = "auto") {
    if (!await p.locator(".assistant-options").evaluate(el => el.open)) await p.locator(".assistant-options > summary").click();
    await p.locator("#assistantSkill").selectOption(skill);
    await p.locator(".assistant-options > summary").click();
    await p.locator("#aiQuestion").fill(text);
    await p.locator("#aiSend").click();
    await p.waitForFunction(() => !document.querySelector("#aiSend").disabled);
  }
  try {
    await p.goto(base);
    await p.locator("#aiAssistant").click();
    await p.waitForSelector('#assistantSkill option[value="product.help"]', {
      state: "attached",
    });
    await send("怎么导出 Word？");
    assert.match(
      await p.locator(".assistant-turn").last().textContent(),
      /product.help/,
    );
    assert.match(
      await p.locator(".assistant-turn").last().innerText(),
      /保存修改/,
    );
    await p.screenshot({ path: `${out}/global-help.png` });
    await send("模型在哪里设置？");
    await p
      .locator(".assistant-turn")
      .last()
      .locator(".assistant-action-links button")
      .first()
      .click();
    await p.waitForSelector("#settingsDialog[open]");
    let r = await p.locator("#settingsDialog").boundingBox();
    await p.mouse.click(r.x - 12, r.y + 20);
    await p.waitForSelector("#settingsDialog", { state: "hidden" });
    await p.locator("#settings").click();
    await p.locator("#model").fill("unsaved-model");
    p.once("dialog", (d) => d.dismiss());
    r = await p.locator("#settingsDialog").boundingBox();
    await p.mouse.click(r.x - 12, r.y + 20);
    assert(await p.locator("#settingsDialog").isVisible());
    assert.equal(await p.locator("#model").inputValue(), "unsaved-model");
    p.once("dialog", (d) => d.accept());
    await p.keyboard.press("Escape");
    await p.waitForSelector("#settingsDialog", { state: "hidden" });
    await send("帮我总结", "note.summary");
    assert.match(
      await p.locator(".assistant-turn").last().innerText(),
      /先选择/,
    );
    await p.locator(".assistant-options > summary").click();
    await p.locator("#skillCatalog").click();
    await p.waitForSelector(".skill-catalog");
    assert.equal(await p.locator("[data-pick-skill]").count(), 7);
    await p.screenshot({ path: `${out}/skill-catalog.png` });
    await p.keyboard.press("Escape");
    await p.locator("#closeAssistant").click();
    await p.locator("#newNote").click();
    await p.locator('[data-input="file"]').click();
    await p.locator("#file").setInputFiles({
      name: "全局助手验收.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(
        "# 全局助手验收\n\n学习率控制参数更新步长，并影响训练过程的稳定性。",
      ),
    });
    await p.locator("#createSubmit").click();
    await p.waitForFunction(() =>
      document.querySelector("#document").textContent.includes("学习率"),
    );
    await p.locator("#notes [data-pin]").first().click();
    assert.equal(
      await p.locator("#notes [data-pin]").first().getAttribute("aria-pressed"),
      "true",
    );
    await p.locator("#aiAssistant").click();
    await send("学习率控制什么？");
    assert.match(
      await p.locator(".assistant-turn").last().textContent(),
      /note.qa/,
    );
    await send("软件当前版本是什么？");
    assert.match(
      await p.locator(".assistant-turn").last().textContent(),
      /product.status/,
    );
    await p.locator("#closeAssistant").click();
    await p.locator("#navigateBack").click();
    await p.waitForSelector("#welcome:not([hidden])");
    await p.locator("#courses").click();
    await p.locator('[data-action="new-course"]').click();
    await p.locator("[data-tool-back]").click();
    await p.waitForSelector('[data-action="new-course"]');
    await p.keyboard.press("Escape");
    await p.reload();
    await p.locator("#aiAssistant").click();
    await p.waitForFunction(() =>
      document
        .querySelector("#assistantHistory")
        .textContent.includes("product.help"),
    );
    await p.setViewportSize({ width: 390, height: 844 });
    await p.screenshot({ path: `${out}/mobile-assistant.png` });
    assert(
      await p.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    );
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      `${out}/result.json`,
      JSON.stringify(
        {
          ok: true,
          global_help_without_note: true,
          skill_trace: true,
          skills: 7,
          backdrop_close: true,
          unsaved_guard: true,
          pinned: true,
          back_navigation: true,
          history_persisted: true,
          reduced_motion: true,
          errors,
        },
        null,
        2,
      ),
    );
    console.log(
      "Global assistant, skills, backdrop, edit protection and navigation passed",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
