// Windows Edge fixture. Every resource is fulfilled locally; no provider,
// source website, model probe or backend mutation can leave this fixture.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const root = path.resolve(__dirname, "..");
const output = path.resolve(process.argv[3] || "build/model-route-ui");
const base = new URL(process.argv[2] || "http://127.0.0.1:8765");
assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname), "Fixture origin must be loopback");
const report = { passed: false, browser: "Microsoft Edge", requests: [], unexpected: [], errors: [], screenshots: [] };
const fixture = { provider: "custom", base_url: "https://fixture.invalid/v1", model: "fixture-model", use_saved_connection: true };
const routeReport = {
  routes: [{ id: "remote_text_model", label: "配置的文字模型", kind: "remote", ready: false, network: "required", detail: "文字连接未配置可用 Key。" }],
  blocking_reasons: [], data_leaving_device: ["source_title", "source_url", "audio", "transcript", "instructions", "selected_frames"],
  offline_source_confirmed: false, local_fallback: { detail: "无 Key 时可选择仅提取字幕。" },
  capability_catalog: {
    text: { detail: "文字：未配置可用连接。" }, vision: { detail: "视觉：尚未验证。" },
    asr: { detail: "ASR：尚未验证该服务和转写型号。" },
    context_limit: { detail: "上下文上限：未知；没有已验证限制。" }, image_limit: { detail: "图片上限：未知；没有已验证限制。" },
  }, estimates: { detail: "费用与耗时区间：未知；尚无可用测量依据。" },
};
(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await context.routeWebSocket("**/*", socket => { report.unexpected.push("WebSocket"); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url()), name = url.pathname;
      const json = value => route.fulfill({ json: value });
      if (url.origin !== base.origin) { report.unexpected.push(`${request.method()} ${url.origin}${name}`); return route.abort("blockedbyclient"); }
      if (request.method() === "GET" && (name === "/" || name.startsWith("/web/"))) {
        const target = path.resolve(root, name === "/" ? "web/index.html" : decodeURIComponent(name.slice(1)));
        assert(target.startsWith(path.join(root, "web") + path.sep));
        const contentType = { ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml" }[path.extname(target)] || "application/octet-stream";
        return route.fulfill({ body: fs.readFileSync(target), contentType });
      }
      report.requests.push(`${request.method()} ${name}`);
      if (request.method() === "GET") {
        if (name === "/health") return json({ ok: true, service: "learnnote", app_version: "0.2.14", llm_model_configured: false,
          default_llm_base_url: fixture.base_url, default_llm_model: fixture.model, default_use_saved_connection: true,
          default_llm_provider: "custom", local_asr_available: false, model_provider_presets: [], assistant_capabilities: {} });
        if (name === "/api/model/connection") return json({ configured: false, storage: "none", model: fixture });
        if (name === "/api/preferences") return json({ task_options: { transcriber: "groq", whisper_model: "whisper-large-v3", visual_understanding: true } });
        if (name === "/api/model/route") return json(routeReport);
        if (name === "/api/tasks") return json({ tasks: [] });
        if (name === "/api/library/materials") return json({ materials: [] });
        if (name === "/api/connections") return json({ openrouter: { connected: false } });
        if (name === "/api/assistant/skills") return json({ skills: [], features: [] });
        if (name === "/api/assistant/history") return json({ items: [] });
        if (name === "/api/update/status") return json({ status: "up_to_date", preferences: { auto_check: false, auto_download: false } });
      }
      if (name === "/api/study/activity" && request.method() === "POST") return json({ ok: true });
      report.unexpected.push(`${request.method()} ${name}`);
      return route.abort("blockedbyclient");
    });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    page.on("pageerror", error => report.errors.push(error.message));
    await page.goto(base.href);
    await page.locator('#welcome[data-ready="true"]').waitFor();
    await page.waitForFunction(() => document.querySelector("#prefTranscriber")?.value === "groq");
    await page.locator("#settings").click();
    await page.locator('[data-settings-section="model"]').click();
    await page.locator("#modelRouteHeading").click();
    await page.locator("#modelRouteCapabilities").filter({ hasText: "图片上限：未知" }).waitFor();
    assert.match(await page.locator("#modelRouteSummary").innerText(), /来源标题.*页面链接.*音频.*字幕文字.*整理要求.*选定画面/);
    assert.match(await page.locator("#modelRouteEstimates").innerText(), /未知.*测量依据/);
    fs.mkdirSync(output, { recursive: true });
    await page.screenshot({ path: path.join(output, "settings.png"), fullPage: true }); report.screenshots.push("settings.png");
    await page.locator("#settingsDialog [data-close]").first().click();
    await page.locator("#newNote").click();
    await page.locator('[data-input="url"]').click();
    for (const mode of ["text", "visual", "subtitles"]) {
      await page.locator(`[name="contentMode"][value="${mode}"]`).check();
      const disclosure = await page.locator("#contentModeExplanation").innerText();
      if (mode === "subtitles") assert.match(disclosure, /不调用转写或总结模型.*没有字幕时停止/);
      else {
        assert.match(disclosure, /音频.*fixture\.invalid.*与文字模型共用地址.*字幕.*整理要求.*fixture\.invalid.*无 Key/);
        assert.equal(disclosure.includes("选定画面"), mode === "visual");
        assert.match(disclosure, /费用与耗时区间未知/);
      }
      await page.screenshot({ path: path.join(output, `${mode}.png`), fullPage: true }); report.screenshots.push(`${mode}.png`);
    }
    await page.locator("#createDialog [data-close]").first().click();
    await page.locator("#newNote").click();
    assert.match(await page.locator("#contentModeExplanation").innerText(), /不调用转写或总结模型/);
    await page.locator("#createDialog [data-close]").first().click();
    // Obtain the real local planner's public declaration; no SDK/client/key.
    const declared = JSON.parse(execFileSync("python", ["-c", [
      "import json",
      "from app.models import TaskOptions",
      "from app.model_route import plan_route",
      "print(json.dumps(plan_route(TaskOptions(llm_base_url='https://api.groq.com/openai/v1', llm_model='qwen/qwen3.8-27b', vision_batch_size=4))))",
    ].join("\n")], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "backend") }, encoding: "utf8" }));
    Object.assign(fixture, { base_url: "https://api.groq.com/openai/v1", model: "qwen/qwen3.8-27b" });
    routeReport.capability_catalog.image_limit = declared.capability_catalog.image_limit;
    routeReport.vision_batch_plan = declared.vision_batch_plan;
    report.declaredImageLimit = declared.vision_batch_plan;
    assert.equal(report.declaredImageLimit.effective_size, 3);
    assert.equal(report.declaredImageLimit.image_limit.status, "declared");
    await page.reload();
    await page.locator('#welcome[data-ready="true"]').waitFor();
    await page.locator("#settings").click();
    await page.locator('[data-settings-section="model"]').click();
    if (!await page.locator("#modelRouteCapabilities").isVisible()) await page.locator("#modelRouteHeading").click();
    await page.locator("#refreshModelRoute").click();
    await page.locator("#modelRouteCapabilities").filter({ hasText: "实际每批最多 3 张" }).waitFor();
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const theme of ["light", "dark"]) {
        await page.evaluate(dark => document.body.classList.toggle("dark", dark), theme === "dark");
        const detail = page.locator("#modelRouteCapabilities");
        await detail.scrollIntoViewIfNeeded();
        assert.match(await detail.innerText(), /官方声明.*未实测.*上下文限制仍未检查.*设置每批 4 张.*实际每批最多 3 张/);
        assert(await detail.evaluate(node => node.scrollWidth <= node.clientWidth + 1), "Declaration must wrap within settings");
        const file = `declared-limit-${width}-${theme}.png`;
        await page.screenshot({ path: path.join(output, file), fullPage: true }); report.screenshots.push(file);
      }
    }
    await require("./model-data-consent-visual.cjs")(page, output, report);
    assert.deepEqual(report.errors, []);
    assert.deepEqual(report.unexpected, []);
    assert(!report.requests.some(value => /setup\/check|\/prepare|tasks\/from/.test(value)));
    report.passed = true;
  } finally {
    fs.mkdirSync(output, { recursive: true });
    fs.writeFileSync(path.join(output, "report.json"), JSON.stringify(report, null, 2));
    await browser.close();
  }
  console.log("PASS: no-key readiness, declared image-count batching, visible uncertainty and data disclosure; no model/source requests");
})().catch(error => { console.error(error); process.exitCode = 1; });
