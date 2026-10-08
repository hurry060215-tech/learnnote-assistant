import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const tools = readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");
assert.match(tools, /分类仅按关键词提示，不代表事实判断/);
assert.match(tools, /community-context\/export/);
assert.match(tools, /delete-community-item/);
assert.match(tools, /\$\{esc\(item.text\)\}/);
assert.doesNotMatch(tools.slice(tools.indexOf("async function community()"), tools.indexOf("function relationshipGraph")), /author_label/);
console.log("Community lane has independent export/delete and non-factual labeling");
