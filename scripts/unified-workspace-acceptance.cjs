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
    await p.locator("#file").setInputFiles({
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
    await p.locator("#unifiedExportStatus").filter({ hasText: "预览已更新" }).waitFor();
    for (const format of ["html", "docx", "pdf"]) {
      await p.locator("#unifiedExportFormat").selectOption(format);
      const response = p.waitForResponse((candidate) =>
        candidate.request().method() === "POST" &&
        candidate.url().includes(`/api/tasks/`) &&
        candidate.url().endsWith(`/exports/${format}`),
      );
      await p.locator("#downloadUnifiedExport").click();
      const exportResponse = await response;
      assert.equal(exportResponse.ok(), true);
      fs.writeFileSync(`${out}/edition.${format}`, await exportResponse.body());
    }
    assert(
      fs
        .readFileSync(`${out}/edition.html`, "utf8")
        .includes("EXPORT_EDIT_MARKER"),
    );
    assert(fs.statSync(`${out}/edition.docx`).size > 1000);
    assert(fs.statSync(`${out}/edition.pdf`).size > 1000);
    await p.locator("[data-close-tool]").click();
    await p.locator("#courses").click();
    await p.locator(".learning-space-dialog").waitFor({ state: "visible" });
    await p.getByRole("button", { name: "＋ 新建学习空间", exact: true }).click();
    await p.locator('.learning-space-form input[name="title"]').fill("学习方法验收");
    await p.getByRole("button", { name: "保存学习空间", exact: true }).click();
    await p.getByRole("heading", { name: "学习方法验收", exact: true }).waitFor({ state: "visible" });
    await p.getByRole("button", { name: "加入当前资料", exact: true }).click();
    await p.waitForFunction(() => document.querySelector(".learning-space-sources")?.textContent.includes("完整工作台验收"));
    await p.getByRole("button", { name: "练习", exact: true }).click();
    await p.getByText("生成练习预览", { exact: true }).waitFor();
    await p.getByRole("button", { name: "复习计划", exact: true }).click();
    await p.getByText("每日复习量", { exact: true }).waitFor();
    await p.getByRole("button", { name: "暂停计划", exact: true }).click();
    await p.getByRole("button", { name: "继续计划", exact: true }).waitFor();
    await p.getByRole("button", { name: "继续计划", exact: true }).click();
    await p.getByRole("button", { name: "暂停计划", exact: true }).waitFor();
    await p.screenshot({ path: `${out}/learning-space.png` });
    await p.getByRole("button", { name: "关闭学习空间", exact: true }).click();
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
    await p.locator("#aiQuestion").fill("学习率");
    await p.locator("#aiSend").click();
    await p.waitForFunction(() =>
      document
        .querySelector(".assistant-turn:last-child .assistant-answer")
        ?.textContent.includes("参数更新"),
    );
    await p.locator("#closeAssistant").click();
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
    await p.locator('[data-settings-section="storage"]').click();
    await p.locator('[data-settings-page="storage"] summary').click();
    await p.locator("#studyTools").click();
    await p.getByText("调整每日目标与时区", {exact:true}).click();
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
