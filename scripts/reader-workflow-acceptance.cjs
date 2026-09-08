// Deterministic UI regression: generated summaries, honest progress, and sidebar navigation.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
(async () => {
  const base = process.argv[2] || "http://127.0.0.1:18930";
  const out =
    process.argv[3] ||
    fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-reader-"));
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const p = await browser.newPage({
    viewport: { width: 1536, height: 1024 },
    reducedMotion: "reduce",
  });
  const errors = [],
    mediaRequests = [];
  p.on("pageerror", (e) => errors.push(e.message));
  p.on("request", (r) => {
    if (/\/api\/tasks\/[^/]+\/media$/.test(r.url()))
      mediaRequests.push(r.url());
  });
  const tasks = [
    {
      id: "summary-good",
      title: "阅读验收示例：如何判断旅程的价值",
      status: "success",
      phase: "completed",
      summary_source: "llm",
      transcript_path: "transcript.json",
      mode: "subtitle_only",
    },
    {
      id: "summary-retry",
      title: "总结失败后，继续使用已有字幕",
      status: "failed",
      phase: "failed",
      failed_phase: "summarizing",
      error_code: "summary_unavailable",
      summary_source: "local-template",
      transcript_path: "transcript.json",
    },
    {
      id: "waiting",
      title: "浏览器已交接，尚未开始",
      status: "queued",
      phase: "queued",
      awaiting_confirmation: true,
    },
  ].map((t) => ({
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:01:00Z",
    options: {},
    kind: "task",
    ...t,
  }));
  const summary =
    "# 阅读验收示例：如何判断旅程的价值\n\n## 核心结论\n\n这是一份用于检查界面的示例笔记。评价旅行体验，可以分别考察抵达过程、住宿条件和实际活动，避免用价格替代具体判断（[00:53 – 01:00]）。\n\n- **交通与时间**：记录所需时间和换乘步骤。\n- **住宿体验**：区分可核实的设施信息与个人感受。\n- **价格构成**：说明哪些服务包含在价格中。\n\n## 内容大纲\n\n1. 旅程如何抵达目的地\n2. 酒店提供了什么\n3. 哪些体验值得关注\n\n## 旅程与体验\n\n对旅行的理解来自具体经历。笔记应当围绕几个完整主题进行组织，保留重要事实和必要的例子，而不是逐句重复字幕。\n\n## 核对来源\n\n遇到不确定的数字或描述，应回到原始字幕查看上下文。";
  const event = (phase, status, ms) => ({
    event: "stage_timing",
    timestamp: "2026-09-08T10:00:01Z",
    phase,
    status,
    details: { duration_ms: ms },
  });
  let retryCalls = 0;
  await p.route("**/api/tasks", (r) => r.fulfill({ json: { tasks } }));
  await p.route("**/api/library/materials?*", (r) =>
    r.fulfill({ json: { materials: [] } }),
  );
  await p.route("**/api/tasks/*", (r) => {
    const id = new URL(r.request().url()).pathname.split("/").at(-1);
    return tasks.some((t) => t.id === id)
      ? r.fulfill({ json: { task: tasks.find((t) => t.id === id) } })
      : r.continue();
  });
  await p.route("**/api/tasks/*/events?*", (r) =>
    r.fulfill({
      json: {
        events: [
          event("subtitle_probe", "completed", 2300),
          event("media", "skipped", 0),
          event("transcript", "completed", 120),
          event("visual", "skipped", 0),
          event(
            "summary",
            r.request().url().includes("retry") ? "failed" : "completed",
            9200,
          ),
        ],
      },
    }),
  );
  await p.route("**/api/tasks/editions/task/*", (r) =>
    r.fulfill({
      json: {
        text: r.request().url().endsWith("waiting")
          ? ""
          : r.request().url().endsWith("summary-retry")
            ? "# 字幕摘录\n\n## 原始字幕\n这是尚未总结的字幕。"
            : summary,
        revision: "fixture",
        edited: false,
      },
    }),
  );
  await p.route("**/api/personal/task/*", (r) =>
    r.fulfill({ json: { annotations: [] } }),
  );
  await p.route("**/api/tasks/*/transcript", (r) =>
    r.fulfill({
      json: {
        segments: [
          { start: 0, end: 4, text: "这是可核对的原始字幕。" },
          { start: 53, end: 60, text: "这里是时间引用对应的原始字幕。" },
        ],
      },
    }),
  );
  await p.route("**/api/tasks/summary-retry/retry-summary", (r) => {
    retryCalls++;
    assert.equal(r.request().method(), "POST");
    return r.fulfill({ json: { task_id: "summary-retry" } });
  });
  try {
    await p.goto(base);
    await p.waitForSelector(".recent-note");
    assert.equal(await p.locator(".recent-note > svg").count(), 0);
    assert.equal(await p.locator("#navigateBack").isVisible(), false);
    await p.locator("#collapseSidebar").click();
    assert.equal(await p.locator("#sidebar").isVisible(), false);
    await p.reload();
    assert.equal(await p.locator("#sidebar").isVisible(), false);
    await p.locator("#menu").click();
    assert.equal(await p.locator("#sidebar").isVisible(), true);
    await p.screenshot({
      path: path.join(out, "home.png"),
      animations: "disabled",
    });
    await p.locator('[data-recent="0"]').click();
    await p.waitForFunction(
      () =>
        document.querySelector('[data-stage="media"]')?.dataset.state ===
        "skipped",
    );
    assert.match(await p.locator("#document").innerText(), /核心结论/);
    assert.match(await p.locator("#taskStatus").innerText(), /无需下载/);
    assert.equal(
      await p
        .locator("#navigateBack")
        .evaluate((el) => getComputedStyle(el).cursor),
      "pointer",
    );
    await p.screenshot({
      path: path.join(out, "reader.png"),
      animations: "disabled",
    });
    await p
      .getByRole("button", { name: "查看原文 [00:53 – 01:00]", exact: true })
      .click();
    await p
      .locator('.cue.active[data-time="53"]')
      .waitFor({ state: "visible" });
    assert.equal(await p.locator("#player").isVisible(), false);
    await p.locator("#closeSource").click();
    await p.locator('[data-task-action="diagnostics"]').click();
    await p.locator(".processing-records").waitFor({ state: "visible" });
    await p.getByText("诊断详情与日志下载", { exact: true }).click();
    assert(await p.getByRole("link", { name: "逐步日志 JSON" }).isVisible());
    await p.screenshot({
      path: path.join(out, "processing-log.png"),
      animations: "disabled",
    });
    await p.locator("[data-close-tool]").click();
    await p.locator("#source").click();
    assert.equal(await p.locator("#player").isVisible(), false);
    await p.locator(".cue").first().waitFor({ state: "visible" });
    assert.match(await p.locator("#sourceContent").innerText(), /原始字幕/);
    assert.equal(mediaRequests.length, 0);
    await p.locator("#closeSource").click();
    await p.locator("#openOutline").click();
    assert.equal(await p.locator("[data-heading]").count(), 4);
    await p.locator('[data-heading="1"]').click();
    await p.locator('#notes [data-id="summary-retry"]').click();
    await p.locator(".transcript-draft").waitFor({ state: "visible" });
    assert.equal(
      await p.locator(".transcript-draft").getAttribute("open"),
      null,
    );
    await p.locator('[data-task-action="retry-summary"]').click();
    assert.equal(retryCalls, 1);
    await p.locator('#notes [data-id="waiting"]').click();
    assert.match(await p.locator("#taskStatus").innerText(), /还没有开始处理/);
    assert.equal(
      await p.locator('#taskStatus [data-stage][data-state="done"]').count(),
      0,
    );
    await p.screenshot({
      path: path.join(out, "confirmation.png"),
      animations: "disabled",
    });
    await p.setViewportSize({ width: 390, height: 844 });
    await p.locator("#menu").click();
    await p.locator('#notes [data-id="summary-good"]').click();
    assert.equal(await p.locator("#sidebar").evaluate((el) => el.inert), true);
    assert(
      await p.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await p.screenshot({
      path: path.join(out, "reader-mobile.png"),
      animations: "disabled",
    });
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      path.join(out, "result.json"),
      JSON.stringify(
        {
          passed: true,
          retryCalls,
          mediaRequests,
          errors,
          viewports: ["1536x1024", "390x844"],
        },
        null,
        2,
      ),
    );
    console.log(JSON.stringify({ passed: true, out }));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
