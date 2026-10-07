const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

async function main() {
  const output = path.resolve(process.argv[2] || "build/task-stream-reconnect-ui");
  fs.mkdirSync(output, { recursive: true });
  const webRoot = path.resolve(__dirname, "..", "web");
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
    let url;
    try {
      url = new URL(request.url || "/", "http://127.0.0.1");
    } catch {
      response.writeHead(400).end();
      return;
    }
    const taskRoot = `/api/tasks/${taskId}`;
    if (request.method === "GET" && url.pathname.startsWith("/web/")) {
      let relativePath;
      try {
        relativePath = decodeURIComponent(url.pathname.slice("/web/".length));
      } catch {
        response.writeHead(400).end();
        return;
      }
      const filePath = path.resolve(webRoot, relativePath);
      if (filePath !== webRoot && !filePath.startsWith(`${webRoot}${path.sep}`)) {
        response.writeHead(403).end();
        return;
      }
      fs.readFile(filePath, (error, body) => {
        if (error) {
          response.writeHead(404).end();
          return;
        }
        const extension = path.extname(filePath).toLowerCase();
        const contentType = extension === ".html" ? "text/html; charset=utf-8"
          : extension === ".js" ? "text/javascript; charset=utf-8"
            : extension === ".css" ? "text/css; charset=utf-8"
              : extension === ".svg" ? "image/svg+xml"
                : "application/octet-stream";
        response.writeHead(200, { "Content-Type": contentType, "Cache-Control": "no-store" });
        response.end(body);
      });
      return;
    }
    if (request.method === "GET" && ["/health", "/api/health"].includes(url.pathname)) {
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ ok: true, status: "healthy" }));
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/tasks") {
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ tasks: [task] }));
      return;
    }
    if (url.pathname === `${taskRoot}/events/stream`) {
      requests.push({ after: url.searchParams.get("after"), lastEventId: request.headers["last-event-id"] || "" });
      const frame = frames[requests.length - 1];
      if (!frame) {
        response.writeHead(404).end();
        return;
      }
      task = { ...task, status: frame.status, phase: frame.phase, progress: frame.progress, message: frame.message, updated_at: now() };
      const payload = JSON.stringify({ task_id: taskId, timestamp: task.updated_at, status: frame.status, phase: frame.phase, progress: frame.progress, message: frame.message, details: { progress: frame.progress }, event_id: frame.id });
      response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
      response.write(`${requests.length === 1 ? "retry: 120\n\n" : ""}id: ${frame.id}\nevent: ${frame.event}\ndata: ${payload}\n\n`);
      setTimeout(() => response.end(), 40);
      return;
    }
    if (request.method === "GET" && url.pathname === taskRoot) {
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ task }));
      return;
    }
    response.writeHead(404, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ detail: "unimplemented isolated acceptance route" }));
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
