const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
(async () => {
  const base = process.argv[2] || "http://127.0.0.1:18780";
  const out = process.argv[3] || "build/redesign-ui";
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 960 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  try {
    await page.goto(base);
    await page.locator("#newNote").click();
    await page.locator('[data-input="file"]').click();
    const text =
      "# 理解梯度下降\n\n梯度下降根据当前位置的梯度，逐步调整参数。\n\n## 学习率控制步长\n\n步长过大可能越过低点，步长过小则收敛缓慢。\n\n```python\n# 原始代码\nrate = 0.01\n```\n\n" +
      Array.from(
        { length: 105 },
        (_, i) => `第 ${i + 1} 段：保留完整的材料内容 END_${i + 1}`,
      ).join("\n\n");
    await page
      .locator("#file")
      .setInputFiles({
        name: "梯度下降.md",
        mimeType: "text/markdown",
        buffer: Buffer.from(text),
      });
    await page.locator("#createSubmit").click();
    await page.waitForSelector("#reading:not([hidden])");
    await page.waitForFunction(() =>
      document.querySelector("#document").textContent.includes("END_105"),
    );
    assert.match(await page.locator("#document pre").innerText(), /# 原始代码/);
    await page.locator("#edit").click();
    await page
      .locator("#noteText")
      .fill(text + "\n\n我的修订：使用不同步长比较更新轨迹。\n");
    await page.locator("#save").click();
    await page.waitForSelector("#editor", { state: "hidden" });
    await page.reload();
    await page.waitForFunction(() =>
      document.querySelector("#document").textContent.includes("我的修订"),
    );
    await page.locator("#annotationText").fill("下次核对课程中的例子。");
    await page.locator("#annotationForm button").click();
    await page.waitForFunction(() =>
      document
        .querySelector("#annotationList")
        .textContent.includes("下次核对"),
    );
    await page.locator("#source").click();
    await page.waitForFunction(() =>
      document.querySelector("#sourceContent").textContent.includes("END_105"),
    );
    assert(
      !(await page.locator("#sourceContent").textContent()).includes(
        "我的修订",
      ),
    );
    await page.locator("#closeSource").click();
    await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({ path: path.join(out, "reading-desktop.png") });
    await page.locator("#theme").click();
    await page.screenshot({ path: path.join(out, "reading-dark.png") });
    await page.locator("#theme").click();
    await page.locator("#newNote").click();
    await page.screenshot({ path: path.join(out, "create.png") });
    await page.locator("#createDialog [data-close]").click();
    await page.setViewportSize({ width: 390, height: 844 });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    );
    await page.screenshot({ path: path.join(out, "reading-mobile.png") });
    await page.locator("#menu").click();
    assert(await page.locator("#newNote").isVisible());
    await page.locator("#settings").click();
    await page.waitForSelector("#settingsDialog[open]");
    await page.locator("#settingsDialog [data-close]").click();
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      path.join(out, "result.json"),
      JSON.stringify(
        {
          ok: true,
          errors,
          full_source: true,
          revision_survives_reload: true,
          mobile_overflow: false,
        },
        null,
        2,
      ),
    );
    console.log(
      "Redesign reading, editing, source, annotation, mobile and theme checks passed",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
