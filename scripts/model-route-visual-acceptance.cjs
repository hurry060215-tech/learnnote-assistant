// Windows Edge fixture. Every resource is fulfilled locally; no provider,
// source website, model probe or backend mutation can leave this fixture.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const output = path.resolve(process.argv[3] || "build/model-route-ui");
const base = new URL(process.argv[2] || "http://127.0.0.1:8765");
assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname), "Fixture origin must be loopback");
const report = { passed: false, browser: "Microsoft Edge", requests: [], unexpected: [], errors: [], screenshots: [] };
const fixture = { provider: "custom", base_url: "https://fixture.invalid/v1", model: "fixture-model", use_saved_connection: true };
const routeReport = {
  routes: [{ id: "remote_text_model", label: "配置的文字模型", kind: "remote", ready: false, network: "required", detail: "文字连接未配置可用 Key。" }],
  blocking_reasons: [], data_leaving_device: ["audio", "transcript", "instructions", "selected_frames"],
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
    assert.match(await page.locator("#modelRouteSummary").innerText(), /音频.*字幕文字.*整理要求.*选定画面/);
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
    assert.deepEqual(report.errors, []);
    assert.deepEqual(report.unexpected, []);
    assert(!report.requests.some(value => /setup\/check|\/prepare|tasks\/from/.test(value)));
    report.passed = true;
  } finally {
    fs.mkdirSync(output, { recursive: true });
    fs.writeFileSync(path.join(output, "report.json"), JSON.stringify(report, null, 2));
    await browser.close();
  }
  console.log("PASS: no-key readiness, visible uncertainty and pre-submit data disclosure; no model/source requests");
})().catch(error => { console.error(error); process.exitCode = 1; });
