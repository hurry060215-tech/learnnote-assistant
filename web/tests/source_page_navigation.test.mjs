import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const rangeModule = "data:text/javascript;base64," + Buffer.from(readFileSync(new URL("../range-source.js", import.meta.url))).toString("base64");
const load = async file => import("data:text/javascript;base64," + Buffer.from(readFileSync(new URL(`../${file}`, import.meta.url), "utf8").replace(/"\/web\/range-source\.js\?v=[^"]+"/, JSON.stringify(rangeModule))).toString("base64"));
const { sourcePageNavigation } = await load("source-video.js");
const { createSourcePageView } = await load("evidence-source-view.js");
const source = (page_url, extra = {}) => ({ kind: "task", page_url, ...extra });

test("subtitle-only Bilibili links retain original page and documented player part/time", () => {
  const original = "https://www.bilibili.com/video/BV1ABCDEF123?p=3&spm_id_from=fixture#reply";
  const link = sourcePageNavigation(source(original), 12.75), timed = new URL(link.timedHref);
  assert.equal(link.originalHref, original);
  assert.equal(timed.origin, "https://player.bilibili.com");
  assert.equal(timed.searchParams.get("bvid"), "BV1ABCDEF123");
  assert.equal(timed.searchParams.get("p"), "3");
  assert.equal(timed.searchParams.get("t"), "12");
  assert.equal(timed.searchParams.get("autoplay"), "0");
  assert.equal(link.seconds, 12.75);
  assert.equal(new URL(sourcePageNavigation(source("https://www.bilibili.com/video/av123?p=2"), 0).timedHref).searchParams.get("aid"), "123");
});

test("explicit Bilibili content identity is never discarded for a guessed player part", () => {
  for (const original of ["https://www.bilibili.com/video/BV1ABCDEF123?cid=456", "https://www.bilibili.com/video/BV1ABCDEF123?p=3&cid=456"]) {
    const result = sourcePageNavigation(source(original), 12.5);
    assert.equal(result.originalHref, original); assert.equal(result.timedHref, "");
    assert.equal(result.reason, "manual"); assert.equal(result.seconds, 12.5);
  }
});

test("YouTube links keep exact video, playlist and index identity while updating selected time", () => {
  const original = "https://www.youtube.com/watch?v=M7lc1UVf-VE&list=PLfixture&index=2&t=5&start=9#t=1";
  const result = sourcePageNavigation(source(original), 25), timed = new URL(result.timedHref);
  assert.equal(result.originalHref, original);
  for (const [key, value] of Object.entries({ v: "M7lc1UVf-VE", list: "PLfixture", index: "2", t: "25s" })) assert.equal(timed.searchParams.get(key), value);
  assert.equal(timed.searchParams.has("start"), false); assert.equal(timed.hash, "");
  assert.equal(new URL(sourcePageNavigation(source("https://youtu.be/M7lc1UVf-VE?si=fixture"), 7).timedHref).searchParams.get("t"), "7s");
});

test("nested range timestamps use absolute original_start once; legacy start is supported", () => {
  const original = "https://www.youtube.com/watch?v=M7lc1UVf-VE";
  const nested = sourcePageNavigation(source(original, { learning_range: { start: 5, end: 15, original_start: 305, original_end: 315 } }), 2.125);
  assert.equal(nested.seconds, 307.125); assert.equal(new URL(nested.timedHref).searchParams.get("t"), "307s");
  assert.equal(sourcePageNavigation(source(original, { learning_range: { start: 5, end: 15 } }), 2).seconds, 7);
});

test("serialized decimal range endpoints and absolute offsets are exact without widening bounds", () => {
  const page = "https://youtu.be/M7lc1UVf-VE";
  const range = {start: 0.1, end: 0.3};
  const exact = sourcePageNavigation(source(page, {learning_range: range}), 0.2);
  assert.equal(exact.reason, ""); assert.equal(exact.seconds, 0.3);
  assert.equal(sourcePageNavigation(source(page, {learning_range: range}), 0.20000000000000004).reason, "invalid_time");
  const nested = {start: 0.1, end: 0.3, original_start: 305.1, original_end: 305.3};
  const absolute = sourcePageNavigation(source(page, {learning_range: nested}), 0.2);
  assert.equal(absolute.reason, ""); assert.equal(absolute.seconds, 305.3);
  assert.equal(new URL(absolute.timedHref).searchParams.get("t"), "305s");
  assert.equal(sourcePageNavigation(source(page, {learning_range: nested}), 0.20000000000000004).reason, "invalid_time");
  // Check the independent absolute-source bound, not only the local duration.
  for (const absoluteStart of [0.1, 305.1]) {
    const shorterOriginal = {...nested, end: 0.4, original_start: absoluteStart, original_end: absoluteStart === 0.1 ? 0.3 : 305.3};
    assert.equal(sourcePageNavigation(source(page, {learning_range: shorterOriginal}), 0.2).seconds, shorterOriginal.original_end);
    assert.equal(sourcePageNavigation(source(page, {learning_range: shorterOriginal}), 0.20000000000000004).reason, "invalid_time");
  }
});

test("generic HTML pages and signed media are unchanged and explicitly manual", () => {
  for (const original of ["https://course.example.test/lesson?chapterId=2#section", "https://cdn.example.test/a.mp4?token=secret&t=8", "https://www.youtube.com/watch?v=M7lc1UVf-VE&signature=fixture%2Fvalue", "https://www.bilibili.com/video/BV1ABCDEF123?auth_key=fixture&p=2"]) {
    const result = sourcePageNavigation(source(original), 12.5);
    assert.equal(result.originalHref, original); assert.equal(result.timedHref, ""); assert.equal(result.reason, "manual"); assert.equal(result.seconds, 12.5);
  }
});

test("unsafe URLs, credential-bearing URLs and malformed page identity never get timed links", () => {
  for (const value of ["javascript:alert(1)", "data:text/html,test", "file:///tmp/video", "//example.test/a", "https://user:secret@example.test/a", "https://example.test/\npath"]) assert.equal(sourcePageNavigation(source(value), 10), null);
  for (const value of ["https://bilibili.com.evil.test/video/BV1ABCDEF123", "https://www.bilibili.com/video/BV1ABCDEF123?p=2&p=3", "https://www.bilibili.com/video/BV1ABCDEF123?p=0", "https://www.youtube.com/watch?v=M7lc1UVf-VE&v=other", "https://www.youtube.com/shorts/M7lc1UVf-VE"]) assert.equal(sourcePageNavigation(source(value), 10).timedHref, "");
  for (const part of ["", "0x2", "2e1", "+2", "2.0", "-1", "2%20"]) assert.equal(sourcePageNavigation(source(`https://www.bilibili.com/video/BV1ABCDEF123?p=${part}`), 10).timedHref, "");
  assert.equal(sourcePageNavigation(source("https://www.youtube.com:8443/watch?v=M7lc1UVf-VE"), 10).timedHref, "");
  assert.equal(sourcePageNavigation({kind:"material",page_url:"https://example.test"}, 10), null);
});

test("invalid time/range never silently points to the beginning or a guessed offset", () => {
  for (const seconds of [-1, NaN, Infinity, "12", null, Number.MAX_VALUE]) {
    const result = sourcePageNavigation(source("https://youtu.be/M7lc1UVf-VE"), seconds);
    assert.equal(result.timedHref, ""); assert.equal(result.reason, "invalid_time");
  }
  for (const learning_range of [{end:10},{start:-1},{original_start:NaN,start:5}]) assert.equal(sourcePageNavigation(source("https://youtu.be/M7lc1UVf-VE",{learning_range}), 1).reason, "invalid_time");
  assert.equal(sourcePageNavigation(source("https://youtu.be/M7lc1UVf-VE",{learning_range:{start:5,end:15,original_start:305,original_end:315}}), 10.1).reason, "invalid_time");
  assert.equal(sourcePageNavigation(source("https://youtu.be/M7lc1UVf-VE"), undefined).timedHref, "");
});

test("original and timestamp links remain the same keyboard-focusable nodes as time changes", () => {
  class Element { constructor(){this.children=[];} replaceChildren(...nodes){this.children=nodes;} }
  const document = {createElement:()=>new Element()}, container = new Element();
  const render = createSourcePageView({container, source:source("https://youtu.be/M7lc1UVf-VE"), navigation:sourcePageNavigation, timestamp:String, document});
  render(10); const original=container.children[0],timed=container.children[2];
  assert.equal(timed.rel,"noopener noreferrer"); assert.match(timed.href,/t=10s/);
  render(20); assert.equal(container.children[0],original); assert.equal(container.children[2],timed); assert.match(timed.href,/t=20s/);
  const manual = createSourcePageView({container, source:source("https://course.example.test/lesson"), navigation:sourcePageNavigation, timestamp:String, document});
  manual(12); assert.equal(container.children[2].hidden,true); assert.match(container.children[3].textContent,/手动定位到 12/);
});
