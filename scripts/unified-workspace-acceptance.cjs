const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
(async () => {
  const base = process.argv[2] || "http://127.0.0.1:18782";
  const out = process.argv[3] || "build/unified-ui";
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch({ channel: "msedge", headless: true });
  const p = await b.newPage({ viewport: { width: 1440, height: 960 } });
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  p.on("dialog", (d) => d.accept());
  try {
    await p.goto(base);
    await p.waitForSelector("#courses");
    assert.equal(await p.locator('a[href*="classic.html"]').count(), 0);
    await p.locator("#newNote").click();
    await p.locator('[data-input="file"]').click();
    await p
      .locator("#file")
      .setInputFiles({
        name: "完整工作台验收.md",
        mimeType: "text/markdown",
        buffer: Buffer.from(
          "# 完整工作台验收\n\n学习率控制参数更新步长。\n\n## 步长与收敛\n\n较小的学习率可能需要更多次更新。\n",
        ),
      });
    await p.locator("#createSubmit").click();
    await p.waitForSelector("#reading:not([hidden])");
    await p.waitForFunction(() =>
      /学习率|EXPORT_EDIT_MARKER/.test(
        document.querySelector("#document").textContent,
      ),
    );
    await p.locator("#edit").click();
    await p
      .locator("#noteText")
      .fill("# 完整工作台验收\n\n保存后的修订 EXPORT_EDIT_MARKER\n");
    await p.locator("#save").click();
    await p.waitForSelector("#editor", { state: "hidden" });
    await p.locator("#moreTools").click();
    await p.locator('[data-action="exports"]').click();
    for (const format of ["markdown", "docx", "pdf"]) {
      const download = p.waitForEvent("download");
      await p.locator(`[data-export="${format}"]`).click();
      await (await download).saveAs(`${out}/edition.${format}`);
    }
    assert(
      fs
        .readFileSync(`${out}/edition.markdown`, "utf8")
        .includes("EXPORT_EDIT_MARKER"),
    );
    await p.locator("[data-close-tool]").click();
    await p.locator("#courses").click();
    await p.locator('[data-action="new-course"]').click();
    await p.locator("#courseTitle").fill("学习方法验收");
    await p
      .locator('.source-picker input[data-kind="material"]')
      .last()
      .check();
    await p.locator("#courseForm button.primary").click();
    await p.waitForSelector('[data-action="edit-course"]');
    await p.locator('[data-action="pause-course"]').click();
    await p.waitForFunction(() =>
      document
        .querySelector('[data-action="pause-course"]')
        .textContent.includes("继续"),
    );
    await p.locator('[data-action="pause-course"]').click();
    await p.waitForFunction(() =>
      document
        .querySelector('[data-action="pause-course"]')
        .textContent.includes("暂停"),
    );
    await p.screenshot({ path: `${out}/course.png` });
    await p.locator("[data-close-tool]").click();
    await p.locator("#moreTools").click();
    await p.locator('[data-action="propose"]').click();
    await p.waitForSelector("#cardsForm input[data-card-index]");
    await p.locator("#cardsForm button.primary").click();
    await p.waitForFunction(() =>
      document.querySelector("#toolStatus").textContent.includes("已加入"),
    );
    await p.locator("[data-close-tool]").click();
    await p.locator("#moreTools").click();
    await p.locator('[data-action="ask"]').click();
    await p.locator("#question").fill("学习率");
    await p.locator("#askForm button").click();
    await p.waitForFunction(() =>
      document.querySelector("#askResult").textContent.includes("参数更新"),
    );
    await p.locator("[data-close-tool]").click();
    await p.locator("#annotationText").fill("需要编辑的个人补充");
    await p.locator("#annotationForm button").click();
    await p.waitForFunction(() =>
      document
        .querySelector("#annotationList")
        .textContent.includes("需要编辑"),
    );
    await p.locator("#moreTools").click();
    await p.locator('[data-action="annotations"]').click();
    await p.waitForSelector(".annotation-edit");
    await p
      .locator(".annotation-edit textarea")
      .last()
      .fill("已编辑的个人补充");
    await p
      .locator(".annotation-edit")
      .last()
      .locator("button")
      .first()
      .click();
    await p.waitForFunction(() =>
      document.querySelector("#toolStatus").textContent.includes("已更新"),
    );
    await p.locator("[data-close-tool]").click();
    await p.locator("#settings").click();
    await p.locator("#settingsDialog summary").click();
    await p.locator("#studyTools").click();
    await p.waitForSelector("#dailyTarget");
    await p.locator("#dailyTarget").fill("12");
    await p.locator("#planForm button").click();
    await p.waitForFunction(() =>
      document.querySelector("#toolStatus").textContent.includes("已保存"),
    );
    await p.locator("[data-close-tool]").click();
    await p.locator("#settings").click();
    await p.locator("#storageTools").click();
    await p.waitForSelector('[data-action="backup"]');
    await p.locator('[data-action="backup"]').click();
    await p.waitForSelector('a[href*="/api/library/backup/"]');
    await p.screenshot({ path: `${out}/storage.png` });
    await p.locator("[data-close-tool]").click();
    await p.setViewportSize({ width: 390, height: 844 });
    await p.locator("#moreTools").click();
    await p.screenshot({ path: `${out}/tools-mobile.png` });
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
          errors,
          courses: true,
          edition_exports: true,
          proposals: true,
          source_scoped_question: true,
          annotations: true,
          study_plan: true,
          backup: true,
          mobile: true,
        },
        null,
        2,
      ),
    );
    console.log("Unified workspace workflows passed");
  } finally {
    await b.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
