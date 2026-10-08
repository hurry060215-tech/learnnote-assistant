import assert from "node:assert/strict";
import vm from "node:vm";
import { installExtensionScriptLoader } from "./helpers/script-loader.mjs";

const context = vm.createContext({ URL });
const loaded = installExtensionScriptLoader(context);
context.importScripts("capture-classification.js", "capture-ranking.js");
assert.deepEqual(loaded, ["capture-classification.js", "capture-ranking.js"]);
const types = context.LearnNoteCaptureClassification;
const ranking = context.LearnNoteCaptureRanking;
assert.ok(Object.isFrozen(types));
assert.ok(Object.isFrozen(ranking));
assert.equal(context.chrome, undefined);
assert.equal(context.fetch, undefined);
assert.equal(types.classify("blob:https://example.test/video"), "blob");
assert.equal(types.classify("https://example.test/clip.m4s", "video/mp4"), "video");
assert.equal(types.classify("https://example.test/clip.m4s", "audio/mp4"), "audio");
assert.equal(types.classify("https://example.test/clip.m4s"), "fragment");
assert.equal(types.classify("https://example.test/cover.jpg@320w.avi", "video/mp4"), "unknown");
assert.equal(types.filenameFromContentDisposition("attachment; filename=bad.txt; filename*=UTF-8''%E8%AF%BE%E7%A8%8B.mp4"), "课程.mp4");
assert.equal(types.classifyCompletedRequest(
  { url: "https://example.test/stream", type: "fetch" }, "application/octet-stream",
  { Range: "bytes=0-10" }, { "content-range": "bytes 0-10/100" },
), "video");
const guessed = Array.from(types.inferSiblingManifestUrls("https://cdn.example.test/course/video/seg.m4s?fixture=1"));
assert.equal(guessed[0], "https://cdn.example.test/course/video/manifest.mpd?fixture=1");
assert.ok(guessed.includes("https://cdn.example.test/course/master.m3u8?fixture=1"));
const current = { url: "https://cdn.example.test/current.mp4", kind: "video", source: "activeVideo", playback_session_rank: 3 };
const other = { url: "https://cdn.example.test/high.m3u8", kind: "hls", source: "webRequest", score: 100 };
assert.equal([other, current].sort(ranking.compareResourceCandidates)[0], current);
assert.equal(ranking.playbackSessionRank(
  { frame_url: "https://course.example.test/old" },
  { page_url: "https://course.example.test/new" },
  { url: "https://course.example.test/new" },
), 0);
const merged = ranking.mergeResource(
  { ...current, user_selected: true, current_time: 0, request_headers: { Referer: "https://course.example.test" } },
  { ...current, score: 90, request_headers: { Accept: "video/mp4" } },
);
assert.equal(merged.user_selected, true);
assert.equal(merged.current_time, 0);
assert.equal(merged.request_headers.Referer, "https://course.example.test");
assert.equal(merged.request_headers.Accept, "video/mp4");
const bad = vm.createContext({ URL });
installExtensionScriptLoader(bad);
assert.throws(() => bad.importScripts("capture-ranking.js"), /undefined/);
assert.throws(() => bad.importScripts("https://example.test/injected.js"), /Unexpected extension import/);
console.log("Pure capture policy, resource compatibility and classic load order pass");
