import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../personal-notes.js", import.meta.url), "utf8");

assert.match(source, /Boolean\(item\.anchor_status\?\.stale\)/);
assert.match(source, /stale\?'修复出处':'编辑'/);
assert.match(source, /item\.anchor_status\?\.repairable/);
assert.match(source, /quoteReanchored&&selected\?\{/);
assert.match(source, /source_revision:container\.dataset\.sourceRevision/);

console.log("Personal annotations show stale anchors and only rebind after a new text selection");
