import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const html = fs.readFileSync(path.join(root, "web", "index.html"), "utf8");
const app = fs.readFileSync(path.join(root, "web", "app.js"), "utf8");
const css = fs.readFileSync(path.join(root, "web", "experience.css"), "utf8");

test("experience layer loads last and keeps four purpose-led mobile destinations", () => {
  const editorialIndex = html.indexOf("/web/editorial.css");
  const experienceIndex = html.indexOf("/web/experience.css");
  assert.ok(editorialIndex >= 0 && experienceIndex > editorialIndex);
  assert.equal((html.match(/class="nav-item(?: active)?"/g) || []).length, 4);
  for (const label of ["开始", "资料库", "复习", "设置"]) assert.match(html, new RegExp(`>${label}<`));
  assert.doesNotMatch(html, /data-app-view="history"/);
  assert.match(css, /grid-template-columns:\s*repeat\(4, minmax\(0, 1fr\)\)/);
  assert.match(css, /height:\s*calc\(76px \+ env\(safe-area-inset-bottom\)\)/);
  assert.match(css, /\.nav-item span,[\s\S]*display:\s*block !important/);
});

test("glass stays on chrome while note reading remains opaque", () => {
  assert.match(css, /\.topbar,[\s\S]*backdrop-filter:\s*blur\(18px\)/);
  assert.match(css, /\.markdown-note\s*\{[\s\S]*background:\s*#fff !important/);
  assert.match(css, /@supports not \(\(-webkit-backdrop-filter/);
  assert.match(css, /@media \(prefers-reduced-transparency: reduce\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\.editorial-intro \.editorial-kicker\s*\{\s*display:\s*none/);
  assert.match(css, /body\.theme-dark\.workspace-mode #workspace\.workspace-panel/);
  assert.match(css, /body\.theme-dark \.study-proposal-dialog/);
  assert.match(css, /body\[data-ui-density="200"\] \.nav-item span/);
});

test("empty library exposes one primary action without implementation jargon", () => {
  assert.match(app, /function emptyTaskQueueHtml\(\)[\s\S]*新建第一篇笔记/);
  assert.match(app, /function emptyResultWorkbench\(\)[\s\S]*这里会保存你的学习笔记/);
  const resultEmpty = /function emptyResultWorkbench\(\)\s*\{([\s\S]*?)\n\}/.exec(app)?.[1] || "";
  assert.equal((resultEmpty.match(/data-empty-source=/g) || []).length, 1);
  assert.doesNotMatch(resultEmpty, /ffmpeg|yt-dlp|Whisper|HLS|DASH/);
});

test("task updates prefer SSE and retain polling fallback", () => {
  assert.match(app, /events\/stream\?after=\$\{cursor\}/);
  assert.match(app, /taskEventStreamCursors\.set\(taskId, eventCursor\)/);
  assert.match(app, /failures >= 3[\s\S]*fallbackMs: 15000/);
  assert.match(app, /activeTasks\.every\(task => taskEventStreamOpen\.has\(task\.id\)\) \? 8000 : 1800/);
  assert.match(app, /closeTaskEventStreams\(\);[\s\S]*scheduleUiPoll\(30000\)/);
  assert.match(app, /experience\.outerHTML = taskProgressExperienceHtml\(task\)/);
});

test("reader progressively enhances Markdown with semantic note evidence", () => {
  assert.match(app, /\/note-document`/);
  assert.match(app, /function noteDocumentEvidenceHtml/);
  assert.match(app, /data-note-section-id=/);
  assert.match(app, /lastNoteDocumentCacheKey === cacheKey/);
  assert.match(app, /草稿可阅读/);
  assert.match(app, /role="progressbar"/);
});

test("local materials and study dashboard reuse live application data", () => {
  assert.match(html, /id="editorialKnowledgeImport"/);
  assert.match(html, /导入 PDF \/ Markdown 学习资料/);
  assert.match(app, /editorialKnowledgeImport\?\.addEventListener/);
  assert.match(app, /\/api\/library\/materials\/import/);
  assert.match(app, /\/api\/library\/materials\?limit=50/);
  assert.match(app, /function openLibraryMaterial/);
  assert.match(html, /id="studyViewDashboard"/);
  assert.match(app, /reviewedToday \/ dailyTarget/);
  assert.match(app, /studyViewProgressBar\.style\.width/);
  assert.match(app, /studyViewRequestGeneration/);
  assert.match(app, /idempotency_key/);
  assert.match(html, /id="docxExportButton"[\s\S]*Word 文档/);
  assert.match(html, /id="pdfExportButton"[\s\S]*打印级 PDF/);
});
