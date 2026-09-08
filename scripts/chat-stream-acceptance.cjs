const { chromium } = require("playwright");
const http = require("node:http"), assert = require("node:assert/strict"), fs = require("node:fs"), os = require("node:os"), path = require("node:path");
(async () => {
  const base = process.argv[2] || "http://127.0.0.1:18940", out = process.argv[3] || path.join(os.tmpdir(), "learnnote-stream-ui");
  const upstream = new URL(base);
  assert(upstream.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(upstream.hostname), "Test upstream must be loopback HTTP");
  fs.mkdirSync(out, { recursive: true });
  let releaseFirst, releaseFinal, releaseHistory, requests = 0, aborted = false, delayHistory = true;
  const responses = new Set();
  const server = http.createServer((req, res) => {
    if (req.url === "/api/assistant/history" && delayHistory) {
      delayHistory = false;
      releaseHistory = () => { if (!res.writableEnded && !res.destroyed) { res.writeHead(200, {"Content-Type":"application/json"}); res.end('{"items":[]}'); } };
      return;
    }
    if (req.url === "/api/assistant/execute/stream") {
      requests++; responses.add(res);
      res.on("close", () => { responses.delete(res); if (requests > 1) aborted = true; });
      res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
      const event = (name, value) => res.write("event: " + name + "\ndata: " + JSON.stringify(value) + "\n\n");
      event("start", { state: "thinking", message: "正在准备回答…" });
      releaseFirst = () => event("delta", { text: "第一段已经到达。" });
      releaseFinal = () => {
        event("delta", { text: "\n\n第二段随后到达。" });
        event("result", { answer: "第一段已经到达。\n\n第二段随后到达。", source: "llm", skill: { id: "general.chat", name: "通用问答", requires_source: false, scope: "conversation" }, execution: { state: "completed" } });
        res.end();
      };
      if (requests > 1) releaseFirst();
      return;
    }
    if (!req.url.startsWith("/") || req.url.startsWith("//")) { res.writeHead(400); res.end(); return; }
    // Only the path comes from the browser. The destination is fixed by the
    // local test runner; absolute/network-path URLs cannot change its host.
    const proxy = http.request({ hostname: upstream.hostname, port: upstream.port, path: req.url, method: req.method, headers: { ...req.headers, host: upstream.host } }, (up) => { res.writeHead(up.statusCode, up.headers); up.pipe(res); });
    proxy.on("error", () => { res.writeHead(502); res.end(); });
    req.pipe(proxy);
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const p = await browser.newPage({ viewport: { width: 1440, height: 960 } }), errors = [];
    p.on("pageerror", (e) => errors.push(e.message));
    await p.goto("http://127.0.0.1:" + server.address().port);
    await p.locator("#aiAssistant").click();
    assert.equal(await p.locator(".assistant-options").evaluate((el) => el.open), false);
    assert.equal(await p.locator(".brand small").count(), 0);
    assert.equal(await p.locator("#wideAssistant").count(), 0);
    await p.locator("#aiQuestion").fill("说明如何理解一个概念");
    await p.locator("#aiSend").click();
    await p.waitForSelector(".assistant-thinking:not([hidden])");
    assert(await p.locator("#aiSend").isDisabled());
    while (!releaseFirst) await new Promise((r) => setTimeout(r, 10));
    releaseFirst();
    await p.waitForFunction(() => document.querySelector(".streaming-turn .assistant-answer")?.textContent.includes("第一段"));
    releaseHistory?.();
    await p.waitForTimeout(50);
    assert(await p.locator(".streaming-turn").isVisible(), "Late history cannot remove an active answer");
    assert(!(await p.locator(".streaming-turn").innerText()).includes("第二段"));
    await p.locator("#closeAssistant").click();
    await p.locator("#aiAssistant").click();
    assert(await p.locator("#aiSend").isDisabled());
    await p.locator("#aiQuestion").fill("保留下一条草稿");
    await p.screenshot({ path: path.join(out, "streaming.png"), animations: "disabled" });
    releaseFinal();
    await p.waitForFunction(() => !document.querySelector("#aiSend").disabled);
    assert.equal(await p.locator("#aiQuestion").inputValue(), "保留下一条草稿");
    assert((await p.locator(".assistant-answer").last().innerText()).includes("第二段"));
    await p.locator("#aiSend").click();
    await p.waitForSelector("#aiStop:not([hidden])");
    await p.waitForFunction(() => document.querySelector(".streaming-turn .assistant-answer")?.textContent.includes("第一段"));
    await p.locator("#aiStop").click();
    await p.waitForFunction(() => !document.querySelector("#aiSend").disabled);
    assert((await p.locator(".assistant-turn").last().innerText()).includes("已停止"));
    for (let i = 0; i < 50 && !aborted; i++) await new Promise((r) => setTimeout(r, 10));
    assert(aborted, "Stop must abort underlying HTTP stream");
    await p.locator("#aiQuestion").fill("旧来源的未完成回答");
    aborted = false;
    await p.locator("#aiSend").click();
    await p.waitForFunction(() => !document.getElementById("aiStop").hidden);
    await p.locator("#closeAssistant").click();
    await p.locator('#notes [data-kind="material"]').first().click();
    for (let i = 0; i < 50 && !aborted; i++) await new Promise((r) => setTimeout(r, 10));
    assert(aborted, "Changing source while assistant is hidden must abort its request");
    await p.locator("#aiAssistant").click();
    await p.waitForFunction(() => !document.querySelector('#assistantHistory').textContent.includes('旧来源的未完成回答'));
    assert.deepEqual(errors, []);
    console.log("Thinking, incremental delivery, stop, clean start and draft continuity passed");
  } finally {
    releaseHistory?.();
    for (const response of responses) response.destroy();
    await browser.close();
    await new Promise((r) => server.close(r));
  }
})().catch((e) => { console.error(e); process.exit(1); });
