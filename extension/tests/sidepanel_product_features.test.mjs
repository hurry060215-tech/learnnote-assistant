import assert from "node:assert/strict";
import {createSidepanelHarness} from "./sidepanel_test_harness.mjs";
const h=await createSidepanelHarness();
const panel=h.api;
const grouped=panel.groupSubtitleParagraphs([{start:0,end:1,text:"第一句"},{start:2,end:3,text:"第二句"},{start:10,end:11,text:"停顿后"}]);
assert.equal(grouped.length,2);
assert.equal(grouped[0].length,2);
assert.equal(grouped[1][0].start,10);
assert.match(panel.subtitleSrt([{start:1.25,end:62.5,text:"原始字幕"}]),/00:00:01,250 --> 00:01:02,500/);
assert.equal(panel.processingOptions("deep").visual_understanding,true);
assert.equal(panel.processingOptions("quick").summary_depth,"brief");
console.log("Sidepanel preserves processing presets and exports precise SRT timing");

h.elements.set("#extensionStyle",{value:"code"});
h.elements.set("#extensionTemplate",{value:"cornell"});
h.elements.set("#extensionPrompt",{value:"保留原文代码"});
const configured=panel.processingOptions("study");
assert.equal(configured.note_style,"code");
assert.equal(configured.note_template,"cornell");
assert.equal(configured.note_profile_prompt,"保留原文代码");

assert.match(panel.renderQuickMarkdown("- `01:25` 讨论学习率"),/data-seek-time="85"/);
