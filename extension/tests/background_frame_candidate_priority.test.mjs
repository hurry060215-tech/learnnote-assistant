import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function listener() {
  return { addListener() {} };
}

const context = {
  console,
  Date,
  URL,
  chrome: {
    webRequest: {
      onBeforeSendHeaders: listener(),
      onHeadersReceived: listener(),
      onBeforeRedirect: listener(),
      onCompleted: listener(),
      onErrorOccurred: listener()
    },
    tabs: { onRemoved: listener(), onUpdated: listener(), query() {} },
    action: { onClicked: listener() },
    runtime: { onMessage: listener() },
    webNavigation: { getAllFrames() {} },
    sidePanel: { open() {} },
    scripting: { executeScript() {} },
    cookies: { getAll() {} }
  }
};

vm.createContext(context);
const backgroundCode = await readFile(new URL("../background.js", import.meta.url), "utf8");
vm.runInContext(backgroundCode, context);

const top = {
  frame_id: 0,
  title: "Course",
  page_url: "https://course.example.com/lesson",
  resources: [],
  frame_elements: [
    {
      src: "https://www.bilibili.com/blackboard/era/promo.html",
      visibility: "hidden",
      is_visible: false,
      visible_area: 0,
      rendered_width: 1,
      rendered_height: 1
    },
    {
      src: "https://activity.hdslb.com/blackboard/static/promo.html",
      visibility: "visible",
      is_visible: true,
      visible_area: 320 * 180,
      rendered_width: 320,
      rendered_height: 180
    },
    {
      src: "https://mooc1.chaoxing.com/ananas/modules/video/index.html",
      visibility: "visible",
      is_visible: true,
      visible_area: 1280 * 720,
      rendered_width: 1280,
      rendered_height: 720
    }
  ]
};

const biliActivity = {
  frame_id: 2,
  page_url: "https://www.bilibili.com/blackboard/era/promo.html",
  active_video: {
    src: "https://activity.hdslb.com/assets/era.mp4",
    paused: false,
    duration: 12,
    visibility: "visible",
    is_visible: true,
    visible_area: 1920 * 1080
  },
  resources: [{
    url: "https://activity.hdslb.com/assets/era.mp4",
    source: "activeVideo",
    kind: "video",
    mime: "video/mp4",
    is_main_video: true,
    playback_match: "exact-src",
    duration: 12,
    visible_area: 1920 * 1080
  }]
};

const hdslbPromo = {
  frame_id: 3,
  page_url: "https://activity.hdslb.com/blackboard/static/promo.html",
  active_video: {
    src: "https://activity.hdslb.com/assets/short-promo.mp4",
    paused: false,
    duration: 8,
    visibility: "visible",
    is_visible: true,
    visible_area: 320 * 180
  },
  resources: []
};

const chaoxingPlayer = {
  frame_id: 4,
  page_url: "https://mooc1.chaoxing.com/ananas/modules/video/index.html",
  active_video: {
    src: "blob:https://mooc1.chaoxing.com/lesson-1",
    paused: false,
    duration: 1800,
    visibility: "visible",
    is_visible: true,
    visible_area: 1280 * 720
  },
  resources: [{
    url: "https://mooc1.chaoxing.com/ananas/status/play?id=lesson-1",
    source: "pageHookBody",
    kind: "video",
    mime: "video/mp4",
    playback_match: "blob-source",
    is_main_video: true,
    duration: 1800,
    visible_area: 1280 * 720
  }, {
    url: "https://mooc1.chaoxing.com/ananas/poster?id=lesson-1",
    source: "pageHookBody",
    kind: "video",
    mime: "image/png",
    score: 100
  }]
};

const page = context.mergePageContexts(
  { id: 7, url: top.page_url, title: top.title },
  [top, biliActivity, hdslbPromo, chaoxingPlayer]
);

assert.equal(page.active_video.frame_id, 4, "expected the visible Chaoxing lesson iframe to beat activity autoplay frames");
assert.equal(page.active_video.frame_visible, true);
assert.equal(page.active_video.frame_visible_area, 1280 * 720);
assert.equal(page.frames.find(frame => frame.frame_id === 2).visibility, "hidden");

const ranked = context.mergeAndRankResources([
  ...page.resources,
  {
    url: "https://media.obeebee.com/third-party-ad.mp4",
    source: "webRequest",
    kind: "video",
    mime: "video/mp4",
    score: 100,
    frame_url: "https://player.obeebee.com/ad.html",
    duration: 15,
    visible_area: 320 * 180
  }
], page, { id: 7, url: top.page_url });

assert.equal(ranked[0].url, "https://mooc1.chaoxing.com/ananas/status/play?id=lesson-1");
assert.ok(!ranked.some(item => item.mime === "image/png"), "expected image MIME candidates to be filtered");
assert.ok(
  ranked.findIndex(item => item.url.includes("obeebee.com")) > ranked.findIndex(item => item.url.includes("chaoxing.com")),
  "expected third-party advertising video to rank below the learning player"
);

const switchedPage = {
  ...page,
  page_url: "https://www.bilibili.com/video/BV-current/",
  active_video: {
    src: "blob:https://www.bilibili.com/current",
    frame_id: 0,
    frame_url: "https://www.bilibili.com/video/BV-current/",
    paused: false,
    current_time: 18,
    duration: 600
  },
  frames: [{ frame_id: 0, page_url: "https://www.bilibili.com/video/BV-current/" }]
};
const switchedRanked = context.mergeAndRankResources([{
  url: "https://cdn.example.com/old-video.m4s",
  source: "webRequest",
  kind: "video",
  score: 100,
  is_main_video: true,
  playback_match: "range-near-playhead",
  frame_id: 0,
  frame_url: "https://www.bilibili.com/video/BV-old/",
  page_url: "https://www.bilibili.com/video/BV-old/"
}, {
  url: "https://cdn.example.com/current-video.m4s",
  source: "webRequest",
  kind: "video",
  score: 60,
  frame_id: 0,
  frame_url: "https://www.bilibili.com/video/BV-current/",
  page_url: "https://www.bilibili.com/video/BV-current/"
}], switchedPage, { id: 7, url: switchedPage.page_url });

assert.equal(switchedRanked[0].url, "https://cdn.example.com/current-video.m4s", "expected the current playback document to beat a high-score resource cached from the previous video");
assert.equal(switchedRanked[0].playback_session_rank, 3);
assert.equal(switchedRanked[1].playback_session_rank, 0);
