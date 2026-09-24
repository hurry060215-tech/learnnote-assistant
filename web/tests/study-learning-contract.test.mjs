import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const learning = readFileSync(new URL("../learning.js", import.meta.url), "utf8");
const app = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const tools = readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");
const desk = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
const html = readFileSync(new URL("../classic.html", import.meta.url), "utf8");

assert.match(html, /今天的证据测验与复习/);
assert.match(html, /自我解释只记录复习动作，不保存回答文本/);
assert.match(learning, /回答不会发送给模型/);
assert.match(learning, /onSelfAssessment\?\./);
assert.match(desk, /id="reviewReflection"/);
assert.match(desk, /kind: "self_assessment"/);
assert.match(desk, /anchor_status\?\.stale/);
assert.match(desk, /修复出处并保存/);
assert.match(desk, /data-annotation-delete/);
assert.match(desk, /data-annotation-edit/);
assert.match(desk, /state\.annotationQuoteReanchored/);
assert.match(readFileSync(new URL("../index.html", import.meta.url), "utf8"), /id="captureAnnotationQuote"/);
assert.match(learning, /card\.source_evidence_ids/);
assert.match(app, /kind: "self_assessment"/);
assert.match(tools, /exportBackup\.href = "\/api\/study\/backup"/);
assert.match(tools, /api\("\/api\/study\/backup\/restore"/);
assert.match(tools, /现有条目不会被覆盖/);
assert.match(tools, /全部资料卡片：新卡/);
assert.match(tools, /近 14 天的本地学习活动/);

console.log("Study cards keep self-assessment local and return to evidence");
