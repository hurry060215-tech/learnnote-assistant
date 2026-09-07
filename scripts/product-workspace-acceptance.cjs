const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("fs");
(async () => {
  const base = process.argv[2] || "http://127.0.0.1:18786",
    out = process.argv[3] || "build/product-ui";
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch({ channel: "msedge", headless: true });
  const p = await b.newPage({ viewport: { width: 1440, height: 960 } });
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  try {
    await p.goto(base);
    await p.waitForSelector("#runtimeModel", { state: "attached" });
    await p.waitForFunction(
      () => document.querySelector("#welcome").dataset.ready === "true",
    );
    assert(await p.locator("#aiAssistant").isVisible());
    const contrast = await p
      .locator(".home-modes button.active")
      .evaluate((el) => {
        const style = getComputedStyle(el),
          rgb = (value) =>
            value
              .match(/[\d.]+/g)
              .slice(0, 3)
              .map(Number);
        const lum = (value) =>
          rgb(value)
            .map((v) => {
              v /= 255;
              return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
            })
            .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
        const a = lum(style.color),
          b = lum(style.backgroundColor);
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      });
    assert(contrast >= 4.5);

    await p.screenshot({ path: `${out}/home.png` });
    await p.locator("#settings").click();
    assert.equal(await p.locator("[data-settings-section]").count(), 6);
    await p.locator('[data-settings-section="notes"]').click();
    await p.locator("#prefStyle").selectOption("code");
    await p.locator("#prefTemplate").selectOption("cornell");
    await p
      .locator("#prefCustom")
      .fill("保留原文中的代码步骤，不编造运行结果。");
    await p.locator("#savePreferences").click();
    await p.waitForFunction(() =>
      document
        .querySelector("#preferencesStatus")
        .textContent.includes("已保存"),
    );
    const pref = await (await p.request.get(base + "/api/preferences")).json();
    assert.equal(pref.task_options.note_style, "code");
    assert.equal(pref.task_options.note_template, "cornell");
    await p.screenshot({ path: `${out}/settings-notes.png` });
    await p.locator('[data-settings-section="model"]').click();
    await p.screenshot({ path: `${out}/settings-model.png` });
    await p.locator("#settingsDialog [data-close]").click();
    await p.locator("#newNote").click();
    await p.locator('[data-input="file"]').click();
    await p.locator("#file").setInputFiles({
      name: "产品工作台验收.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(
        "# 产品工作台\n\n学习率控制参数更新步长，选择合适的学习率有助于稳定训练。\n\n## 操作步骤\n\n先检查原始数据，再观察参数更新和损失变化。",
      ),
    });
    await p.locator("#createSubmit").click();
    await p.waitForFunction(() =>
      document.querySelector("#document").textContent.includes("学习率"),
    );
    await p.locator("#aiAssistant").click();
    await p.locator("#aiQuestion").fill("学习率控制什么？");
    await p.locator("#aiSend").click();
    await p.waitForFunction(
      () =>
        !document.querySelector("#aiSend").disabled &&
        document
          .querySelector(".assistant-turn:last-child .assistant-answer")
          ?.textContent.includes("学习率"),
    );
    assert.match(
      await p.locator(".assistant-answer").last().innerText(),
      /学习率/,
    );
    await p.locator(".assistant-turn:last-child .save-ai-note").click();
    await p.waitForFunction(() =>
      document.querySelector("#annotationList").textContent.includes("学习率"),
    );
    await p.screenshot({ path: `${out}/assistant.png` });
    await p.locator("#closeAssistant").click();
    await p.locator("#openOutline").click();
    await p.waitForSelector(".outline-tree button");
    await p.locator("#outlineDialog header button").click();
    await p.setViewportSize({ width: 390, height: 844 });
    await p.locator("#aiAssistant").click();
    assert(
      await p.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    );
    await p.screenshot({ path: `${out}/assistant-mobile.png` });
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      `${out}/result.json`,
      JSON.stringify(
        {
          ok: true,
          visible_assistant: true,
          settings_sections: 6,
          preferences_persisted: true,
          assistant_source_answer: true,
          save_answer: true,
          outline: true,
          mobile: true,
          errors,
        },
        null,
        2,
      ),
    );
    console.log("Product workspace acceptance passed");
  } finally {
    await b.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
