import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const tools = readFileSync(new URL("../community-browser.js", import.meta.url), "utf8");
assert.match(tools, /分类仅按本页关键词提示，不代表事实判断/);
assert.match(tools, /\$\{path\}\/export/);
assert.match(tools, /delete-community-item/);
assert.match(tools, /\$\{esc\(item.text\)\}/);
assert.doesNotMatch(tools, /author_label/);
console.log("Community lane has independent export/delete and non-factual labeling");
