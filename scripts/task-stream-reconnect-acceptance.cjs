const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

async function main() {
  const upstream = new URL(process.argv[2] || "http://127.0.0.1:8765");
  const backendOrigin = `${upstream.protocol}//${upstream.host}`;
  const output = path.resolve(process.argv[3] || "build/task-stream-reconnect-ui");
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  const taskId = "sse-reconnect-acceptance-fixture";
  const now = () => new Date().toISOString();
  let task = {
    id: taskId,
    source_type: "page_text",
    mode: "page_text",
    title: "UI stream reconnect acceptance",
    page_url: "https://example.com/public-lesson",
    status: "running",
    phase: "queued",
    progress: 1,
    message: "Waiting for first stream update",
    created_at: now(),
    updated_at: now(),
    options: { visual_understanding: false },
  };
  const requests = [];
  const frames = [
    { id: 1, event: "task_updated", status: "running", phase: "fetching_subtitles", progress: 25, message: "First connection reached" },
    { id: 2, event: "task_updated", status: "running", phase: "transcribing", progress: 65, message: "Progress resumed after reconnect" },
    { id: 3, event: "task_terminal", status: "success", phase: "completed", progress: 100, message: "Completed after reconnect" },
  ];
  page.on("pageerror", error => errors.push(error.message));

  const proxy = http.createServer((request, response) => {
    const url = new URL(request.url || "/", "http://127.0.0.1");
    const taskRoot = `/api/tasks/${taskId}`;
    if (request.method === "GET" && url.pathname === "/api/tasks") {
      response.writeHead(200, { "Content-Type": "application/json" });
      return response.end(JSON.stringify({ tasks: [task] }));
    }
    if (url.pathname === `${taskRoot}/events/stream`) {
      requests.push({ after: url.searchParams.get("after"), lastEventId: request.headers["last-event-id"] || "" });
      const frame = frames[requests.length - 1];
      if (!frame) {
        response.writeHead(404);
        return response.end();
      }
      task = { ...task, status: frame.status, phase: frame.phase, progress: frame.progress, message: frame.message, updated_at: now() };
      const payload = JSON.stringify({ task_id: taskId, timestamp: task.updated_at, status: frame.status, phase: frame.phase, progress: frame.progress, message: frame.message, details: { progress: frame.progress }, event_id: frame.id });
      response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
      response.write(`${requests.length === 1 ? "retry: 120\n\n" : ""}id: ${frame.id}\nevent: ${frame.event}\ndata: ${payload}\n\n`);
      return setTimeout(() => response.end(), 40);
    }
    if (request.method === "GET" && url.pathname === taskRoot) {
      response.writeHead(200, { "Content-Type": "application/json" });
      return response.end(JSON.stringify({ task }));
    }
    const target = new URL(`${url.pathname}${url.search}`, backendOrigin);
    const proxied = http.request(target, { method: request.method, headers: request.headers }, upstreamResponse => {
      response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
      upstreamResponse.pipe(response);
    });
    proxied.on("error", () => {
      if (!response.headersSent) response.writeHead(502);
      response.end();
    });
    request.pipe(proxied);
  });

  await new Promise(resolve => proxy.listen(0, "127.0.0.1", resolve));
  const address = proxy.address();
  const base = `http://127.0.0.1:${address.port}/web/classic.html`;
  try {
    await page.goto(base, { waitUntil: "domcontentloaded" });
    if (await page.locator("#skipOnboardingButton").isVisible()) await page.locator("#skipOnboardingButton").click();
    if (await page.locator("#confirmReleaseNotesButton").isVisible()) await page.locator("#confirmReleaseNotesButton").click();
    const card = page.locator(`.task[data-id="${taskId}"]`);
    await card.waitFor({ state: "visible", timeout: 10000 });
    await page.waitForFunction(id => document.querySelector(`.task[data-id="${id}"] .task-status-pill`)?.textContent.includes("100%"), taskId, { timeout: 12000 });
    assert.equal(requests.length, 3, JSON.stringify(requests));
    assert.deepEqual(requests.map(item => item.lastEventId), ["", "1", "2"]);
    assert(requests.every(item => item.after === "0"), JSON.stringify(requests));
    assert.match(await card.innerText(), /已完成|完成/);
    assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(output, "task-stream-reconnected.png"), fullPage: true });
    process.stdout.write(JSON.stringify({ ok: true, streamRequests: requests, finalStatus: task.status, finalProgress: task.progress, errors }));
  } finally {
    await browser.close();
    await new Promise(resolve => proxy.close(resolve));
  }
}

main().catch(error => { process.stderr.write(`${error.stack}\n`); process.exit(1); });
