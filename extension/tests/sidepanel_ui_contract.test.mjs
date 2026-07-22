import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const html = await readFile(new URL("../sidepanel.html", import.meta.url), "utf8");
const css = await readFile(new URL("../sidepanel.css", import.meta.url), "utf8");

assert.match(html, /id="videoTitle"/);
assert.match(html, /aria-label="媒体完整性预检"/);
assert.match(html, /data-kind="video"/);
assert.match(html, /data-kind="audio"/);
assert.match(html, /data-kind="subtitle"/);
assert.match(html, /id="candidateCount"/);
assert.match(html, /id="durationValue"/);
assert.match(html, /id="sendButton"[\s\S]*发送到客户端/);
assert.match(html, /id="handoffProgress"[^>]*role="progressbar"/);
assert.equal((html.match(/role="progressbar"/g) || []).length, 1);
assert.match(html, /data-client-view="settings"/);
assert.match(html, /data-client-view="diagnostics"/);
assert.doesNotMatch(html, /API Key|切片间隔|视觉窗口|任务历史|导出诊断|候选资源列表/);
assert.match(css, /\.handoff-progress > span[\s\S]*transition: width 240ms ease/);
assert.match(css, /font-family: Inter, "SF Pro Text", "Segoe UI Variable"/);
