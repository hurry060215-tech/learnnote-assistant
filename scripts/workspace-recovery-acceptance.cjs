// Browser plugin not available: use the repository's Playwright + Edge workflow.
// Flow: write a scoped draft -> reload/retry -> inspect an earlier generation,
// while preserving current note content and avoiding all real model calls.
const { chromium } = require("playwright");
const assert = require("node:assert/strict"),
  fs = require("node:fs"),
  os = require("node:os"),
  path = require("node:path");
(async () => {
  const base = process.argv[2] || "http://127.0.0.1:18950";
  const out =
    process.argv[3] || path.join(os.tmpdir(), "learnnote-workspace-recovery");
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 960 },
    reducedMotion: "reduce",
  });
  const errors = [],
    mutations = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let historyFails = false,
    syncFails = false,
    versionFails = false,
    answerFails = false,
    releaseVersion;
  const id = "recovery0123",
    version = "a".repeat(64),
    stamp = "2026-09-09T10:00:00+00:00";
  const note = {
    id,
    title: "旅行笔记 · 当前修订",
    status: "success",
    source_type: "page_text",
    summary_source: "llm",
    note_path: "note.md",
    created_at: stamp,
    updated_at: stamp,
    options: { content_mode: "text" },
  };
  const current =
    "# 旅行笔记 · 当前修订\n\n这是保留的当前正文。\n\n## 行程\n\n当前行程经过个人修改。";
  const markdown =
    "# 旅行笔记 · 第一次生成\n\n## 原始行程\n\n- 上午抵达。\n- 下午参观。\n\n历史内容用于核对。";
  const reply = {
    answer: "可以在笔记上方打开导出入口。",
    source: "local",
    skill: {
      id: "product.help",
      name: "使用帮助",
      requires_source: false,
      scope: "product",
    },
    execution: { state: "completed" },
  };
  await page.route("**/api/**", async (route) => {
    const req = route.request(),
      url = new URL(req.url()),
      p = url.pathname;
    const json = (value, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(value),
      });
    if (p === "/api/assistant/history")
      return json(
        historyFails ? { detail: "模拟读取失败" } : { items: [] },
        historyFails ? 503 : 200,
      );
    if (p === "/api/assistant/execute/stream")
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          "event: result\ndata: " +
          JSON.stringify(
            answerFails
              ? {
                  ...reply,
                  answer: "模型尚未配置",
                  execution: { state: "needs_configuration" },
                }
              : reply,
          ) +
          "\n\n",
      });
    if (p === "/api/tasks") return syncFails ? json({detail: "模拟同步中断"}, 503) : json({ tasks: [note] });
    if (p === "/api/library/materials") return json({ materials: [] });
    if (p === `/api/tasks/editions/task/${id}`)
      return json({ text: current, revision: 2, edited: true });
    if (p === `/api/personal/task/${id}`) return json({ annotations: [] });
    if (p === `/api/tasks/${id}/qa`) return json({ items: [] });
    if (p === `/api/tasks/${id}/events`) return json({ events: [] });
    if (p === `/api/tasks/${id}/summary-versions`)
      return json(
        versionFails
          ? { detail: "模拟版本读取失败" }
          : {
              task_id: id,
              versions: [
                {
                  id: version,
                  title: "旅行笔记 · 第一次生成",
                  created_at: stamp,
                  size_bytes: 120,
                  current: false,
                },
              ],
              current_note_available: true,
            },
        versionFails ? 503 : 200,
      );
    if (p === `/api/tasks/${id}/summary-versions/${version}`) {
      if (releaseVersion)
        await new Promise((resolve) => {
          releaseVersion.resolve = resolve;
        });
      return json({
        task_id: id,
        id: version,
        title: "旅行笔记 · 第一次生成",
        created_at: stamp,
        markdown,
      });
    }
    if (req.method() !== "GET") {
      mutations.push(p);
      assert.equal(p, "/api/assistant/route", "Unexpected real API mutation");
    }
    return route.continue();
  });
  try {
    await page.goto(base);
    assert.match(await page.title(), /LearnNote/);
    await page.waitForFunction(
      () => document.querySelector("#welcome")?.dataset.ready === "true",
    );
    assert(
      (await page.locator("body").innerText()).includes("今天，想学些什么"),
    );
    assert.equal(
      await page.locator("vite-error-overlay, nextjs-portal").count(),
      0,
    );
    await page.locator("#aiAssistant").click();
    await page.locator("#aiQuestion").fill("刷新后保留全局草稿");
    await page.reload();
    await page.locator("#aiAssistant").click();
    assert.equal(
      await page.locator("#aiQuestion").inputValue(),
      "刷新后保留全局草稿",
    );
    assert.match(await page.locator("#aiStatus").innerText(), /已恢复/);
    await page.locator(`#notes [data-id="${id}"]`).click();
    await page.waitForFunction(() =>
      document
        .querySelector("#document")
        .textContent.includes("当前行程经过个人修改"),
    );
    assert.equal(await page.locator("#aiQuestion").inputValue(), "");
    await page.locator("#aiQuestion").fill("这份笔记的独立草稿");
    await page.reload();
    await page.waitForFunction(() =>
      document
        .querySelector("#document")
        .textContent.includes("当前行程经过个人修改"),
    );
    await page.locator("#aiAssistant").click();
    assert.equal(
      await page.locator("#aiQuestion").inputValue(),
      "这份笔记的独立草稿",
    );
    await page.locator(".brand").click();
    assert.equal(
      await page.locator("#aiQuestion").inputValue(),
      "刷新后保留全局草稿",
    );
    await page.locator("#aiQuestion").fill("怎么导出笔记？");
    answerFails = true;
    await page.locator("#aiQuestion").press("Control+Enter");
    await page.waitForFunction(
      () =>
        !document.querySelector("#aiSend").disabled &&
        document
          .querySelector("#assistantHistory")
          .textContent.includes("模型尚未配置"),
    );
    assert.equal(
      await page.locator("#aiQuestion").inputValue(),
      "怎么导出笔记？",
    );
    answerFails = false;
    await page.locator("#aiSend").click();
    await page.waitForFunction(
      () => document.querySelector("#aiQuestion").value === "",
    );
    await page.reload();
    await page.locator("#aiAssistant").click();
    assert.equal(await page.locator("#aiQuestion").inputValue(), "");
    await page.locator("#aiQuestion").fill("网络恢复后继续发送");
    historyFails = true;
    await page.locator("#closeAssistant").click();
    await page.locator("#aiAssistant").click();
    await page.getByRole("button", { name: "重新读取记录" }).waitFor();
    assert.equal(
      await page.locator("#aiQuestion").inputValue(),
      "网络恢复后继续发送",
    );
    historyFails = false;
    await page.getByRole("button", { name: "重新读取记录" }).click();
    await page.waitForFunction(() =>
      document
        .querySelector("#assistantHistory")
        .textContent.includes("有什么想问"),
    );
    await page.locator("#closeAssistant").click();
    await page.locator(`#notes [data-id="${id}"]`).click();
    await page.locator("#openVersions").click();
    await page.locator("[data-summary-version]").first().click();
    await page.locator(".summary-version-preview h2").waitFor();
    assert.match(
      await page.locator(".summary-version-preview").innerText(),
      /上午抵达/,
    );
    assert.match(
      await page.locator("#document").innerText(),
      /当前行程经过个人修改/,
    );
    const download = page.waitForEvent("download");
    await page.locator("[data-download-version]").click();
    const file = await download;
    await file.saveAs(path.join(out, "history.md"));
    assert.equal(
      fs.readFileSync(path.join(out, "history.md"), "utf8"),
      markdown,
    );
    await page.screenshot({
      path: path.join(out, "history-desktop.png"),
      animations: "disabled",
    });
    await page.locator("[data-version-back]").click();
    releaseVersion = {};
    await page.locator("[data-summary-version]").first().click();
    await page.waitForFunction(() =>
      document
        .querySelector("#summaryVersionsBody")
        .textContent.includes("正在读取历史内容"),
    );
    await page.locator("[data-version-back]").click();
    while (!releaseVersion.resolve)
      await new Promise((resolve) => setTimeout(resolve, 10));
    releaseVersion.resolve();
    releaseVersion = null;
    await page.waitForTimeout(100);
    assert.equal(
      await page.locator("[data-summary-version]").count(),
      1,
      "Late preview must not replace the returned list",
    );
    await page.keyboard.press("Escape");
    versionFails = true;
    await page.locator("#openVersions").click();
    await page.locator("[data-retry-versions]").waitFor();
    versionFails = false;
    await page.locator("[data-retry-versions]").click();
    await page.locator("[data-summary-version]").waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator("[data-summary-version]").click();
    await page.locator(".summary-version-preview h2").waitFor();
    await page.screenshot({
      path: path.join(out, "history-mobile.png"),
      animations: "disabled",
    });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    );
    await page.keyboard.press("Escape");
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.locator("#edit").click();
    await page.locator("#noteText").fill("# 同步中断时仍然保留的修改");
    syncFails = true;
    await page.locator("#refresh").click();
    await page.locator("#connectionStatus:not([hidden])").waitFor();
    assert.equal(await page.locator("#noteText").inputValue(), "# 同步中断时仍然保留的修改");
    syncFails = false;
    await page.locator("#connectionStatus").click();
    await page.waitForFunction(() => document.getElementById("connectionStatus").hidden);
    assert.equal(await page.locator("#noteText").inputValue(), "# 同步中断时仍然保留的修改");
    assert.deepEqual(errors, []);
    console.log(
      "PASS: scoped drafts reload, cleared delivered input, retained configuration failure, history retry, generated version preview/download, stale preview guard, desktop/mobile",
    );
  } finally {
    releaseVersion?.resolve?.();
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
