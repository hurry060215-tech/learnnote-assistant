// Actual default workspace and OCR panel in Edge, with controlled local APIs.
// No provider, real video, external website or backend mutation leaves this fixture.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const root = path.resolve(__dirname, "..");
const base = new URL(process.argv[2] || "http://127.0.0.1:8765");
const output = path.resolve(process.argv[3] || "build/screen-subtitle-ui");
assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname), "Fixture origin must be loopback");
const settings = { crop_left: 0, crop_top: .74, crop_right: 1, crop_bottom: 1, interval_seconds: .5, language: "auto" };
const source = { id: "source", title: "Synthetic OCR source", source_type: "local", mode: "local", status: "success", phase: "completed", progress: 100,
  options: { content_mode: "text", visual_understanding: false }, summary_source: "text-llm", updated_at: "2026-10-10T00:00:00Z", message: "Synthetic saved video source" };
const tasks = [source];
const ocr = { ...source, id: "ocr-result", title: "Synthetic OCR result", mode: "screen_subtitles", status: "cancelled", phase: "cancelled", source_task_id: "source",
  options: { content_mode: "subtitles", screen_subtitles: settings, visual_understanding: false }, summary_source: "screen-ocr-extract" };
const report = { passed: false, source_sha: execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim(),
  browser: "Microsoft Edge", surface: "actual default workspace + screen-subtitle dialog", data: "synthetic tasks and controlled API responses; OCR engine checked separately",
  requests: [], unexpected: [], errors: [], screenshots: [], cases: [] };
let previewImage = "", holdPreview = false, releasePreview = null, pendingPreviewReady = null, rejectStart = true;
const retentionError = "无法保留独立视频引用，未开始提取。原资料保持不变；请在支持硬链接且有可用空间的本地资料目录中重试。";
const preview = text => ({ timestamp: 35, frame_timestamp: 35, image_url: previewImage,
  warning: "合成预览：画面字幕 OCR 未人工核验。", lines: [{ text, confidence: .79, selected: true, bbox: [[10,275],[320,275],[320,307],[10,307]], verification: "unreviewed" }] });
const result = () => ({ status: ocr.status === "success" ? "ready" : "cancelled", warning: "画面字幕 OCR 未人工核验，短暂字幕可能遗漏。",
  completed_windows: ocr.status === "success" ? 3 : 1, total_windows: 3, cache_hits: 1,
  coverage: { complete: ocr.status === "success", sampled_seconds: ocr.status === "success" ? 130 : 60, requested_seconds: 130 },
  cues: [{ start: 0, end: 2, text: "学习率 LEARNINGRATE", confidence: .79, sample_count: 4, lines: preview("学习率 LEARNINGRATE").lines }] });
(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await context.routeWebSocket("**/*", socket => { report.unexpected.push("WebSocket"); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url()), name = url.pathname, method = request.method();
      const json = value => route.fulfill({ json: value });
      if (url.origin !== base.origin) { report.unexpected.push(`${method} ${url.origin}${name}`); return route.abort("blockedbyclient"); }
      if (method === "GET" && (name === "/" || name.startsWith("/web/"))) {
        const target = path.resolve(root, name === "/" ? "web/index.html" : decodeURIComponent(name.slice(1)));
        assert(target.startsWith(path.join(root, "web") + path.sep));
        return route.fulfill({ body: fs.readFileSync(target), contentType: ({ ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml" })[path.extname(target)] || "application/octet-stream" });
      }
      const body = method === "POST" && request.postData() ? request.postDataJSON() : null;
      report.requests.push({ method, path: name, body });
      if (method === "GET") {
        if (name === "/health") return json({ ok: true, service: "learnnote", app_version: "0.2.14", llm_model_configured: false,
          local_asr_available: false, default_llm_base_url: "", default_llm_model: "", model_provider_presets: [], assistant_capabilities: {} });
        if (name === "/api/tasks") return json({ tasks });
        if (name === "/api/library/materials") return json({ materials: [] });
        if (name === "/api/preferences") return json({ task_options: {} });
        if (name === "/api/model/connection") return json({ configured: false, model: null, storage: "none" });
        if (name === "/api/model/route") return json({ routes: [], estimates: {}, capability_catalog: {}, data_leaving_device: [] });
        if (name === "/api/connections") return json({ openrouter: { connected: false } });
        if (name === "/api/assistant/skills") return json({ skills: [], features: [] });
        if (name === "/api/assistant/history") return json({ items: [] });
        if (name === "/api/update/status") return json({ status: "up_to_date", preferences: { auto_check: false, auto_download: false } });
        if (/^\/api\/tasks\/editions\/task\//.test(name)) return json({ text: "# Synthetic OCR source\n\nOriginal ASR and note remain unchanged.", revision: "fixture-revision", edited: false });
        if (/^\/api\/personal\/task\//.test(name)) return json({ annotations: [] });
        if (name.endsWith("/events")) return json({ events: [] });
        if (name.endsWith("/events/stream")) return route.fulfill({ contentType: "text/event-stream", body: "event: task_terminal\ndata: {}\n\n" });
        if (name.endsWith("/screen-subtitles")) return json(name.includes("ocr-result") ? result() : { status: "not_started" });
        const task = tasks.find(item => name === `/api/tasks/${item.id}`);
        if (task) return json({ task });
      }
      if (method === "POST") {
        if (name === "/api/study/activity") return json({ ok: true });
        if (name.endsWith("/screen-subtitles/preview")) {
          if (holdPreview) { await new Promise(resolve => { releasePreview = resolve; pendingPreviewReady?.(); }); return json(preview("STALE_RESPONSE")); }
          return json(preview("学习率 LEARNINGRATE"));
        }
        if (name === "/api/tasks/source/screen-subtitles") {
          if (rejectStart) { rejectStart = false; return route.fulfill({ status: 409, json: { detail: { code: "screen_ocr_media_retention_failed", message: retentionError } } }); }
          if (!tasks.some(item => item.id === ocr.id)) tasks.push(ocr);
          return json({ task_id: ocr.id, task: ocr, source_task_id: source.id });
        }
        if (name === "/api/tasks/ocr-result/screen-subtitles/resume") {
          ocr.status = "success"; ocr.phase = "completed";
          return json({ task_id: ocr.id, task: ocr, resumed: true });
        }
        if (name === "/api/tasks/ocr-result/cancel") { ocr.status = "cancelled"; return json({ task: ocr }); }
      }
      report.unexpected.push(`${method} ${name}`);
      return route.abort("blockedbyclient");
    });
    const page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on("pageerror", error => report.errors.push(error.message));
    previewImage = await page.evaluate(() => { const canvas = document.createElement("canvas"); canvas.width = 640; canvas.height = 94; const pen = canvas.getContext("2d"); pen.fillRect(0,0,640,94); pen.fillStyle="white"; pen.font="28px sans-serif"; pen.fillText("学习率 LEARNING RATE",20,55); return canvas.toDataURL("image/jpeg"); });
    const capture = async name => { fs.mkdirSync(output,{recursive:true}); await page.screenshot({path:path.join(output,name),fullPage:true}); report.screenshots.push(name); };
    await page.goto(base.href); await page.locator('#welcome[data-ready="true"]').waitFor();
    await page.locator('#notes [data-id="source"]').click(); await page.locator('#document').getByText('Original ASR and note remain unchanged.').waitFor();
    const openPanel = async () => { await page.locator('#moreTools').click(); await page.locator('[data-action="screen-subtitles"]').click(); await page.locator('[data-start-screen]').waitFor({state:'visible'}); await page.waitForFunction(() => !document.querySelector('[data-start-screen]').disabled); };
    await openPanel();
    assert.equal(await page.locator('[name="generateNote"]').isChecked(),false);
    await page.locator('[name="cropTop"]').fill('60'); await page.locator('[name="interval"]').fill('1'); await page.locator('[name="language"]').selectOption('zh'); await page.locator('[name="previewTime"]').fill('35');
    await page.locator('[data-preview-screen]').click(); await page.locator('[data-screen-preview] img').waitFor();
    assert.match(await page.locator('[data-screen-preview]').innerText(),/79%.*未核验/);
    const previewRequest=report.requests.find(item=>item.path.endsWith('/preview'));
    assert.equal(previewRequest.body.settings.crop_top,.6); assert.equal(previewRequest.body.settings.interval_seconds,1); assert.equal(previewRequest.body.settings.language,'zh');
    await capture('desktop-preview.png'); report.cases.push('crop, interval, language and preview confidence');
    await page.locator('[data-start-screen]').click(); await page.getByText(retentionError, {exact:true}).waitFor();
    assert.equal(tasks.length,1); await page.waitForFunction(()=>!document.querySelector('[data-start-screen]').disabled);
    report.cases.push('unsupported media retention shows actionable retry without creating a task');
    await page.locator('[data-start-screen]').click(); await page.waitForFunction(()=>location.hash==='#task/ocr-result');
    const created=report.requests.filter(item=>item.path==='/api/tasks/source/screen-subtitles');assert.equal(created.length,2);assert(created.every(item=>item.body.generate_note===false&&item.body.options===null));
    report.cases.push('explicit start creates a separate result without model opt-in');
    await openPanel(); await page.locator('[data-resume-screen]').click(); await page.locator('[data-screen-result]').getByText('抽样处理完成，识别结果待核对',{exact:true}).waitFor();
    assert.equal(report.requests.filter(item=>item.path.endsWith('/screen-subtitles/resume')).length,1);
    await capture('desktop-resumed.png'); report.cases.push('saved window resume and unreviewed result');
    await page.locator('[data-close-tool]').click();
    await page.locator('#notes [data-id="source"]').click(); await openPanel(); holdPreview=true;
    const previewStarted = new Promise(resolve => { pendingPreviewReady = resolve; });
    await page.locator('[data-preview-screen]').click(); await previewStarted;
    await page.locator('[data-close-tool]').click(); await openPanel();
    assert(releasePreview,'The stale request must have reached the controlled endpoint');
    const oldResponse = page.waitForResponse(response => response.url().endsWith('/screen-subtitles/preview'));
    releasePreview(); holdPreview=false; await oldResponse;
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); assert(!(await page.locator('#toolBody').innerText()).includes('STALE_RESPONSE'));
    report.cases.push('closing and reopening rejects a late preview response');
    await page.setViewportSize({width:390,height:844});
    await page.locator('[data-preview-screen]').click(); await page.locator('[data-screen-preview] img').waitFor();
    await capture('mobile-preview.png');
    const bounds=await page.locator('#toolsDialog').boundingBox();assert(bounds.x>=0&&bounds.x+bounds.width<=391,'Dialog fits mobile viewport');
    assert.equal(await page.locator('[name="generateNote"]').isChecked(),false);
    report.cases.push('390px mobile crop/result controls and default model opt-out');
    assert.deepEqual(report.errors,[]);assert.deepEqual(report.unexpected,[]);
    assert(!report.requests.some(item=>/rerun-from-media|transcrib|download|retry-summary|model\/.*(?:check|prepare)/.test(item.path)));
    report.passed=true;
  } finally {
    if(releasePreview)releasePreview();
    fs.mkdirSync(output,{recursive:true});fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));
    await browser.close();
  }
  console.log('PASS: screen-subtitle preview, explicit start, resume, stale navigation and mobile UI; controlled local APIs only');
})().catch(error=>{console.error(error);process.exitCode=1;});
