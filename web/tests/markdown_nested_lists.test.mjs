import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";
const scope = {};
vm.runInNewContext(readFileSync(new URL("../markdown.js", import.meta.url), "utf8"), scope);
const render = scope.LearnNoteMarkdown.markdownToHtml;

test("actual MiMo four-space bullets stay nested under their numbered hotel topic", () => {
  const result = render("1. **抵达方式**\n    *   该列车需要七小时。\n    *   车内提供餐食（[00:53 – 01:00]）。\n2. **住宿体验**\n    *   保留服务与房间的具体信息。");
  assert.equal(result, '<ol><li><strong>抵达方式</strong><ul><li>该列车需要七小时。</li><li>车内提供餐食（[00:53 – 01:00]）。</li></ul></li><li><strong>住宿体验</strong><ul><li>保留服务与房间的具体信息。</li></ul></li></ol>');
});
test("mixed three-level lists and non-one numbering produce valid parent-child nesting", () => {
  assert.equal(render("3. 第三步\n    - 子项\n        1. 更深的步骤\n    - 另一子项\n4. 下一步"), '<ol start="3"><li>第三步<ul><li>子项<ol><li>更深的步骤</li></ol></li><li>另一子项</li></ul></li><li>下一步</li></ol>');
});
test("blank-separated children and indented continuation paragraphs retain the parent", () => {
  assert.equal(render("- 主题\n\n    - 要点\n      补充解释\n\n- 另一主题\n\n## 独立章节"), '<ul><li>主题<ul><li>要点<p>补充解释</p></li></ul></li><li>另一主题</li></ul><h2 id="note-独立章节">独立章节</h2>');
});
test("nested list content is escaped and fenced code is never parsed into bullets", () => {
  const result = render("- 安全内容\n    * <script>alert(1)</script>\n\n```text\n    * code bullet\n```\n\n- 操作步骤\n    ```text\n    * nested code bullet\n    ```\n- 下一步");
  assert(!result.includes("<script>"));
  assert.match(result, /<li>&lt;script&gt;alert\(1\)&lt;\/script&gt;<\/li>/);
  assert.match(result, /<pre><code>    \* code bullet\n<\/code><\/pre>/);
  assert.match(result, /<li>操作步骤<pre><code>    \* nested code bullet\n<\/code><\/pre><\/li><li>下一步/);
});
test("media safety hooks and headings still work after nested lists", () => {
  scope.LearnNoteMarkdown.configure({ safeNoteMediaUrl: value => value === "/safe.png" ? value : "" });
  const result = render("- item\n    - nested\n\n![可用画面](/safe.png)\n\n![外部画面](https://bad.example/x.png)\n\n# 标题");
  assert.match(result, /<\/ul><\/li><\/ul><figure/);
  assert.match(result, /src="\/safe.png"/);
  assert(!result.includes('src="https://bad.example'));
  assert.match(result, /<h1 id="note-标题">标题<\/h1>/);
});
