// Regression: a source stays readable while the assistant and library resize.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { execFileSync } = require("node:child_process");
(async () => {
  const base = process.argv[2] || "http://127.0.0.1:18940",
    out =
      process.argv[3] ||
      fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-layout-"));
  fs.mkdirSync(out, { recursive: true });
  const root = path.resolve(__dirname, ".."),
    localPython = path.join(
      root,
      ".venv",
      process.platform === "win32" ? "Scripts" : "bin",
      process.platform === "win32" ? "python.exe" : "python",
    );
  const ffmpeg = execFileSync(
    fs.existsSync(localPython) ? localPython : "python",
    ["-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
    { encoding: "utf8" },
  ).trim();
  const fixture = path.join(out, "layout-fixture.mp4");
  execFileSync(ffmpeg, [
    "-hide_banner",
    "-loglevel",
    "error",
    "-f",
    "lavfi",
    "-i",
    "color=c=0x496b66:s=480x270:d=20",
    "-vf",
    "drawgrid=w=80:h=90:t=1:c=white@0.15",
    "-c:v",
    "libx264",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
    "-y",
    fixture,
  ]);
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const p = await browser.newPage({
    viewport: { width: 1536, height: 1024 },
    reducedMotion: "reduce",
  });
  const errors = [],
    consoleErrors = [],
    requests = [];
  p.on("pageerror", (e) => errors.push(e.message));
  p.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  const tasks = [
    {
      id: "layout-video",
      title: "视频与笔记一起阅读",
      media_path: "fixture.mp4",
    },
    { id: "layout-captions", title: "仅字幕笔记", mode: "subtitle_only" },
  ].map((t) => ({
    ...t,
    kind: "task",
    status: "success",
    phase: "completed",
    summary_source: "llm",
    transcript_path: "transcript.json",
    options: {},
    created_at: "2026-09-08T12:00:00Z",
    updated_at: "2026-09-08T12:00:00Z",
  }));
  const summary =
    "# 视频与笔记一起阅读\n\n## 先理解，再核对\n\n打开助手后，视频仍然留在笔记的上方。拖动两侧分隔线，按自己的习惯调整阅读空间。\n\n" +
    Array.from(
      { length: 16 },
      (_, i) =>
        `## 章节 ${i + 1}\n\n这里是一段用于验证阅读的示例内容。视频可以固定在上方，同时保留足够的正文阅读空间。`,
    ).join("\n\n");
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
  await p.route("**/api/tasks/editions/task/*", (r) =>
    r.fulfill({ json: { text: summary, revision: "fixture", edited: false } }),
  );
  await p.route("**/api/tasks/*/events?*", (r) =>
    r.fulfill({ json: { events: [] } }),
  );
  await p.route("**/api/personal/task/*", (r) =>
    r.fulfill({ json: { annotations: [] } }),
  );
  await p.route("**/api/tasks/*/qa", (r) => r.fulfill({ json: { items: [] } }));
  await p.route("**/api/assistant/history", (r) =>
    r.fulfill({ json: { items: [] } }),
  );
  await p.route("**/api/tasks/*/transcript", (r) => {
    requests.push(r.request().url());
    return r.fulfill({
      json: {
        segments: Array.from({ length: 20 }, (_, i) => ({
          start: i,
          end: i + 1,
          text: `第 ${i + 1} 段原始字幕，用于核对时间与内容。`,
        })),
      },
    });
  });
  const media = [];
  await p.route("**/api/tasks/*/media", (r) => {
    media.push(r.request().url());
    const buf = fs.readFileSync(fixture);
    const range = r.request().headers().range;
    if (range) {
      const [start, end] = range.replace("bytes=", "").split("-");
      const a = Number(start),
        b = end ? Number(end) : buf.length - 1;
      return r.fulfill({
        status: 206,
        contentType: "video/mp4",
        headers: {
          "Accept-Ranges": "bytes",
          "Content-Range": "bytes " + a + "-" + b + "/" + buf.length,
        },
        body: buf.subarray(a, b + 1),
      });
    }
    return r.fulfill({
      contentType: "video/mp4",
      headers: { "Accept-Ranges": "bytes" },
      body: buf,
    });
  });
  try {
    await p.goto(base + "/#task/layout-video");
    await p.waitForSelector("#player:not([hidden])");
    await p.waitForFunction(
      () => document.querySelector("#player").readyState >= 2,
    );
    assert.match(await p.title(), /LearnNote/);
    assert.equal(new URL(p.url()).origin, new URL(base).origin);
    assert.match(await p.locator("#document").innerText(), /先理解/);
    assert.equal(
      await p.locator("vite-error-overlay,nextjs-portal").count(),
      0,
    );
    assert(
      await p
        .locator("#sourcePanel")
        .evaluate(
          (el) =>
            el.parentElement.id === "reading" &&
            el.nextElementSibling.id === "document",
        ),
    );
    assert.equal(
      await p.locator("#sourceTranscript").getAttribute("open"),
      null,
    );
    await p.waitForFunction(
      () => document.querySelector("#player").readyState === 4,
    );
    await p.evaluate(() => {
      window.layoutPlayer = document.querySelector("#player");
      window.mediaLoadCount = 0;
      layoutPlayer.addEventListener("loadstart", () => window.mediaLoadCount++);
      layoutPlayer.currentTime = 3;
      return new Promise((resolve) =>
        layoutPlayer.addEventListener(
          "seeked",
          async () => {
            await layoutPlayer.play();
            resolve();
          },
          { once: true },
        ),
      );
    });
    await p.locator("#aiAssistant").click();
    await p.waitForSelector("#assistantPanel:not([hidden])");
    assert(
      await p.evaluate(
        () =>
          window.layoutPlayer === document.querySelector("#player") &&
          !layoutPlayer.paused &&
          layoutPlayer.currentTime >= 3 &&
          window.mediaLoadCount === 0,
      ),
    );
    const rects = await p.evaluate(() => {
      const a = document
          .querySelector("#assistantPanel")
          .getBoundingClientRect(),
        s = document.querySelector("#sourcePanel").getBoundingClientRect();
      return { assistant: a.left, source: s.right, top: a.top, width: s.width };
    });
    assert(rects.source <= rects.assistant);
    assert.equal(rects.top, 0);
    assert(rects.width > 600);
    await p.locator("#pinSource").click();
    assert.equal(
      await p.locator("#pinSource").getAttribute("aria-pressed"),
      "true",
    );
    await p.evaluate(() => scrollTo(0, 1200));
    await p.waitForTimeout(100);
    assert(
      await p.locator("#sourcePanel").evaluate((el) => {
        const r = el.getBoundingClientRect();
        return r.top > 80 && r.top < 200;
      }),
    );
    await p.screenshot({
      path: path.join(out, "center-video-assistant.png"),
      animations: "disabled",
    });
    await p.evaluate(() => window.layoutPlayer.pause());
    async function drag(id, dx) {
      const r = await p.locator(id).boundingBox();
      await p.mouse.move(r.x + r.width / 2, Math.max(150, r.y + 30));
      await p.mouse.down();
      await p.mouse.move(r.x + r.width / 2 + dx, 180, { steps: 8 });
      await p.mouse.up();
    }
    const oldLeft = await p
      .locator("#sidebar")
      .evaluate((el) => el.getBoundingClientRect().width);
    await drag("#sidebarResize", 60);
    assert.equal(
      await p
        .locator("#sidebar")
        .evaluate((el) => el.getBoundingClientRect().width),
      oldLeft + 60,
    );
    const oldRight = await p
      .locator("#assistantPanel")
      .evaluate((el) => el.getBoundingClientRect().width);
    await drag("#assistantResize", -80);
    assert.equal(
      await p
        .locator("#assistantPanel")
        .evaluate((el) => el.getBoundingClientRect().width),
      oldRight + 80,
    );
    await p.locator("#assistantResize").press("ArrowLeft");
    assert.equal(
      await p
        .locator("#assistantPanel")
        .evaluate((el) => el.getBoundingClientRect().width),
      oldRight + 96,
    );
    const saved = await p.evaluate(() =>
      JSON.parse(localStorage.getItem("learnnote.layout.widths")),
    );
    await p.reload();
    await p.waitForSelector("#pinSource");
    assert.equal(
      await p.locator("#pinSource").getAttribute("aria-pressed"),
      "true",
    );
    await p.locator("#aiAssistant").click();
    assert.equal(
      await p
        .locator("#sidebar")
        .evaluate((el) => el.getBoundingClientRect().width),
      saved.sidebar,
    );
    assert.equal(
      await p
        .locator("#assistantPanel")
        .evaluate((el) => el.getBoundingClientRect().width),
      saved.assistant,
    );
    await p.locator("#assistantResize").press("End");
    assert(
      await p
        .locator(".workspace")
        .evaluate((el) => el.getBoundingClientRect().width >= 419),
    );
    assert(
      await p.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await p.screenshot({
      path: path.join(out, "resized-panels.png"),
      animations: "disabled",
    });
    await p.locator("#closeAssistant").click();
    await p.locator("#closeSource").click();
    await p.locator("#aiAssistant").click();
    assert.equal(await p.locator("#sourcePanel").isVisible(), false);
    await p.locator("#closeAssistant").click();
    await p.locator('#notes [data-id="layout-captions"]').click();
    await p.locator("#source").click();
    await p.waitForSelector("#sourceTranscript[open] .cue");
    assert.equal(await p.locator("#player").isVisible(), false);
    assert.equal(await p.locator("#pinSource").isVisible(), false);
    assert(!media.some((url) => url.includes("layout-captions")));
    await p.setViewportSize({ width: 390, height: 844 });
    await p.locator("#closeSource").click();
    await p.locator("#menu").click();
    await p.locator('#notes [data-id="layout-video"]').click();
    await p.waitForSelector("#player:not([hidden])");
    assert.equal(await p.locator("#sidebarResize").isVisible(), false);
    assert.equal(
      await p
        .locator("#sourcePanel")
        .evaluate((el) => getComputedStyle(el).position),
      "static",
    );
    assert(
      await p.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await p.screenshot({
      path: path.join(out, "mobile-video.png"),
      animations: "disabled",
    });
    await p.locator("#aiAssistant").click();
    assert.equal(
      await p
        .locator("#assistantPanel")
        .evaluate((el) => el.getBoundingClientRect().width),
      390,
    );
    assert.equal(await p.locator("#assistantResize").isVisible(), false);
    await p.screenshot({
      path: path.join(out, "mobile-assistant.png"),
      animations: "disabled",
    });
    assert.deepEqual(errors, []);
    assert.deepEqual(consoleErrors, []);
    fs.writeFileSync(
      path.join(out, "result.json"),
      JSON.stringify(
        {
          passed: true,
          base,
          out,
          errors,
          consoleErrors,
          media,
          requests,
          saved,
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
