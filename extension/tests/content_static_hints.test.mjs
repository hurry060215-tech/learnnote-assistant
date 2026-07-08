import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function selectorMatches(element, selector) {
  const item = selector.trim();
  if (item === "*") return true;
  const attrOnly = item.match(/^\[([a-z0-9-]+)\]$/i);
  if (attrOnly) return Boolean(element.getAttribute(attrOnly[1]));
  const attrMatch = item.match(/^([a-z0-9-]+)\[([a-z0-9-]+)\]$/i);
  if (attrMatch) {
    return element.tagName.toLowerCase() === attrMatch[1].toLowerCase() && Boolean(element.getAttribute(attrMatch[2]));
  }
  return element.tagName.toLowerCase() === item.toLowerCase();
}

function collectDescendants(root, selector) {
  const selectors = selector.split(",");
  const results = [];

  function visit(node) {
    for (const child of node.children || []) {
      if (selectors.some(item => selectorMatches(child, item))) results.push(child);
      visit(child);
    }
  }

  visit(root);
  return results;
}

class FakeElement {
  constructor(tagName, attributes = {}, children = []) {
    this.tagName = tagName.toUpperCase();
    this.nodeType = 1;
    this.children = children;
    this.attributes = attributes;
    this.textContent = attributes.textContent || "";
    this.src = attributes.src || "";
    this.href = attributes.href || "";
    this.type = attributes.type || "";
    this.shadowRoot = null;
  }

  getAttribute(name) {
    return this.attributes[name] || "";
  }

  querySelectorAll(selector) {
    return collectDescendants(this, selector);
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  matches(selector) {
    return selector.split(",").some(item => selectorMatches(this, item));
  }

  addEventListener() {}
}

const packedDash = Buffer.from("https://cdn.example.com/static/manifest.mpd?token=b64", "utf8").toString("base64");
const doubleEncodedHls = encodeURIComponent(encodeURIComponent("https://cdn.example.com/static/double/master.m3u8?token=double&uid=2"));
const doubleEncodedNakedVideo = encodeURIComponent(encodeURIComponent("https://cdn.example.com/static/double/naked.mp4?token=naked-double"));
const mixedEncodedVideo = "https%253A//cdn.example.com/static/mixed/lesson.mp4%253Ftoken%253Dmixed";
const pageUrlEncodedHls = encodeURIComponent(encodeURIComponent("https://cdn.example.com/static/page-url/master.m3u8?token=page"));
const pageUrlPackedConfig = Buffer.from(JSON.stringify({
  sources: [{ file: "/static/page-param/lesson.mp4?token=packed" }]
}), "utf8").toString("base64");
const pageHashPlayerConfig = JSON.stringify({
  baseUrl: "https://cdn.example.com/static/hash/",
  streams: { hlsPath: "course/master.m3u8?token=hash", mediaType: "application/vnd.apple.mpegurl" }
});

const player = new FakeElement("div", {
  "data-play-url": "https%3A%2F%2Fcdn.example.com%2Fstatic%2Fmaster.m3u8%3Ftoken%3Dattr"
});
const packedPlayer = new FakeElement("div", {
  "data-video-url": packedDash
});
const playUrlAliasPlayer = new FakeElement("div", {
  "data-playurl": "/static/alias-play.mp4?token=alias"
});
const manifestAliasPlayer = new FakeElement("div", {
  "data-master-url": "/static/alias-master.m3u8?token=master",
  "data-dash-url": "/static/alias-manifest.mpd?token=dash"
});
const backupAliasPlayer = new FakeElement("div", {
  "data-backup-url": "/static/alias-backup.mp4?token=backup",
  "data-download-url": "/static/alias-download.mp4?token=download"
});
const script = new FakeElement("script", {
  textContent: "window.__player={videoUrl:'https%3A%2F%2Fcdn.example.com%2Fstatic%2Flesson.mp4%3Ftoken%3Dscript', flvUrl:'https://cdn.example.com/static/live.flv?token=script'};"
});
const plainEncodedScript = new FakeElement("script", {
  textContent: "window.__payload='https%3A%2F%2Fcdn.example.com%2Fstatic%2Fplain-master.m3u8%3Ftoken%3Dplain%26uid%3D1';"
});
const doubleEncodedPlayer = new FakeElement("div", {
  "data-hls-url": doubleEncodedHls
});
const plainDoubleEncodedScript = new FakeElement("script", {
  textContent: `window.__payload='${doubleEncodedNakedVideo}';`
});
const mixedEncodedScript = new FakeElement("script", {
  textContent: `window.__mixed='${mixedEncodedVideo}';`
});
const jsEscapedScript = new FakeElement("script", {
  textContent: String.raw`window.__playConfig={hls:"https:\u002F\u002Fcdn.example.com\u002Fstatic\u002Fescaped\u002Fmaster.m3u8\u003Ftoken\u003Djs\u0026uid\u003D7",videoUrl:"https:\/\/cdn.example.com\/static\/escaped\/lesson.mp4\x3Fsig\x3Dok"};`
});
const jsEscapedPayloadScript = new FakeElement("script", {
  textContent: String.raw`window.__payload='https:\/\/cdn.example.com\/static\/escaped\/payload.m3u8\x3Ftoken\x3Dpayload';`
});
const nestedMediaKeyPayload = Buffer.from(JSON.stringify({
  streams: {
    hlsUrl: "https://cdn.example.com/static/nested-key/master.m3u8?token=wrapped"
  }
}), "utf8").toString("base64");
const nestedMediaKeyScript = new FakeElement("script", {
  textContent: `window.__wrapped={playInfo:'${nestedMediaKeyPayload}'};`
});
const splitBasePayload = JSON.stringify({
  baseUrl: "https://cdn.example.com/static/split/",
  streams: {
    videoPath: "course/master.m3u8?token=split-static",
    videoMime: "application/vnd.apple.mpegurl"
  }
});
const splitBasePackedPayload = Buffer.from(splitBasePayload, "utf8").toString("base64");
const splitBaseScript = new FakeElement("script", {
  textContent: `window.__split={playInfo:'${splitBasePackedPayload}'};`
});
const endpointContainerScript = new FakeElement("script", {
  textContent: `window.__coursePlayer={
    sources:[
      { file: "/api/play?id=json-array&token=abc" },
      { url: "/ananas/status/objectid-123?flag=normal" }
    ],
    streams:["https://media.example.com/vod/lesson?id=noext"]
  };`
});
const qualityContainerScript = new FakeElement("script", {
  textContent: `window.__qualityPlayer={
    definitions:[{name:"HD", address:"/api/play?id=definition-hd"}],
    qualities:[{name:"720p", play:"/api/play?id=quality-play"}],
    formats:[{file:"/static/formats/lesson.mp4?token=format"}],
    renditions:[{src:"/static/renditions/master.m3u8?token=rendition"}]
  };`
});
const segmentScript = new FakeElement("script", {
  textContent: "window.__segments=['https://cdn.example.com/static/hls/segment-001.ts?token=seg'];"
});
const onclickPlayer = new FakeElement("button", {
  onclick: "openPlayer('https%3A%2F%2Fcdn.example.com%2Fstatic%2Fonclick-master.m3u8%3Ftoken%3Dclick')"
});
const paramPlayer = new FakeElement("div", {
  "data-params": "objectid=ignored&play=https%3A%2F%2Fcdn.example.com%2Fstatic%2Fparam-lesson.mp4%3Ftoken%3Dparam"
});
const lazyPathPlayer = new FakeElement("div", {
  "data-path": "/ananas/status/objectid-lazy?flag=normal"
});
const lazyUriPlayer = new FakeElement("div", {
  "data-uri": "/vod/play?id=uri-lazy&token=ok"
});
const ordinaryPathLink = new FakeElement("a", {
  "data-path": "/ordinary/page"
});
const configPlayer = new FakeElement("div", {
  "data-config": "open('/static/plain-attr.mp4?token=attr-plain')"
});
const nakedPlayer = new FakeElement("div", {
  "data-options": "load(/static/naked-master.m3u8?token=naked);"
});
const vendorPlayer = new FakeElement("div", {
  "vendor-player-json": JSON.stringify({
    course: "lesson",
    sources: [{ url: "https://cdn.example.com/static/vendor/master.m3u8?token=vendor" }]
  })
});
const preloadVideo = new FakeElement("link", {
  rel: "preload",
  as: "video",
  href: "/opaque/video-stream?id=preload"
});
const preloadHls = new FakeElement("link", {
  rel: "preload",
  type: "application/vnd.apple.mpegurl",
  href: "/opaque/playlist?id=typed-hls"
});
const prefetchPlayApi = new FakeElement("link", {
  rel: "prefetch",
  as: "fetch",
  href: "/api/play?id=prefetch"
});
const ogVideo = new FakeElement("meta", {
  property: "og:video",
  content: "/opaque/og-stream?id=meta"
});
const htmlVideo = new FakeElement("video", {
  src: "/api/play?id=html5&token=abc"
}, [
  new FakeElement("source", {
    type: "application/vnd.apple.mpegurl",
    src: "/opaque/html5-hls?id=42"
  }),
  new FakeElement("source", {
    type: "application/dash+xml",
    "data-src": "/opaque/html5-dash?id=42"
  }),
  new FakeElement("track", {
    kind: "subtitles",
    src: "/caption?id=html5"
  })
]);
const plainUrlScript = new FakeElement("script", {
  textContent: "window.__payload='https://cdn.example.com/static/plain-url.m3u8?token=script-plain';"
});
const srcdocIframe = new FakeElement("iframe", {
  title: "Inline player",
  srcdoc: String.raw`<script>window.__player={hls:"https:\/\/cdn.example.com\/static\/iframe-srcdoc\/master.m3u8\x3Ftoken\x3Dsrcdoc"};</script>`
});
const sameOriginIframe = new FakeElement("iframe", {
  title: "Same origin player"
});
sameOriginIframe.contentDocument = {
  documentElement: {
    outerHTML: String.raw`<html><body><script>window.__player={videoUrl:"https:\/\/cdn.example.com\/static\/iframe-doc\/lesson.mp4\x3Ftoken\x3Ddoc"};</script></body></html>`
  },
  body: {
    innerText: "",
    textContent: ""
  }
};
const html = new FakeElement("html", {}, [player, packedPlayer, playUrlAliasPlayer, manifestAliasPlayer, backupAliasPlayer, doubleEncodedPlayer, onclickPlayer, paramPlayer, lazyPathPlayer, lazyUriPlayer, ordinaryPathLink, configPlayer, nakedPlayer, vendorPlayer, preloadVideo, preloadHls, prefetchPlayApi, ogVideo, htmlVideo, script, plainEncodedScript, plainDoubleEncodedScript, mixedEncodedScript, jsEscapedScript, jsEscapedPayloadScript, nestedMediaKeyScript, splitBaseScript, endpointContainerScript, qualityContainerScript, segmentScript, plainUrlScript, srcdocIframe, sameOriginIframe]);

let messageListener = null;
const context = {
  console,
  URL,
  URLSearchParams,
  Node: { ELEMENT_NODE: 1 },
  location: { href: `https://course.example.com/lesson?objectid=${pageUrlEncodedHls}&player=${encodeURIComponent(pageUrlPackedConfig)}#viewer?payload=${encodeURIComponent(pageHashPlayerConfig)}` },
  document: {
    title: "Static hints lesson",
    readyState: "complete",
    documentElement: html,
    body: { innerText: "Course body" },
    querySelectorAll(selector) {
      return collectDescendants({ children: [html] }, selector);
    },
    addEventListener() {}
  },
  window: null,
  chrome: {
    runtime: {
      onMessage: {
        addListener(listener) {
          messageListener = listener;
        }
      },
      sendMessage() {
        return Promise.resolve();
      }
    }
  },
  MutationObserver: class {
    observe() {}
  },
  performance: {
    getEntriesByType() {
      return [
        {
          name: "https://course.example.com/api/play?id=perf",
          initiatorType: "fetch",
          encodedBodySize: 2048,
          transferSize: 4096
        },
        {
          name: "https://mooc1.chaoxing.com/ananas/status/objectid-perf?flag=normal",
          initiatorType: "xmlhttprequest",
          encodedBodySize: 4096,
          transferSize: 8192
        },
        {
          name: "https://course.example.com/lesson-data?id=not-media",
          initiatorType: "fetch",
          encodedBodySize: 2048,
          transferSize: 4096
        }
      ];
    }
  },
  atob: value => Buffer.from(value, "base64").toString("binary"),
  setTimeout() {
    return 0;
  },
  clearTimeout() {},
  setInterval() {
    return 0;
  }
};

context.window = context;
context.window.addEventListener = () => {};
context.window.postMessage = () => {};

vm.createContext(context);
const contentCode = await readFile(new URL("../content.js", import.meta.url), "utf8");
vm.runInContext(contentCode, context);

let response = null;
messageListener({ type: "collect-page-data" }, {}, data => {
  response = data;
});

const hls = response.resources.find(item => item.url === "https://cdn.example.com/static/master.m3u8?token=attr");
const pageUrlHls = response.resources.find(item => item.url === "https://cdn.example.com/static/page-url/master.m3u8?token=page");
const pageUrlPackedVideo = response.resources.find(item => item.url === "https://course.example.com/static/page-param/lesson.mp4?token=packed");
const pageHashHls = response.resources.find(item => item.url === "https://cdn.example.com/static/hash/course/master.m3u8?token=hash");
const dash = response.resources.find(item => item.url === "https://cdn.example.com/static/manifest.mpd?token=b64");
const aliasPlayVideo = response.resources.find(item => item.url === "https://course.example.com/static/alias-play.mp4?token=alias");
const aliasMasterHls = response.resources.find(item => item.url === "https://course.example.com/static/alias-master.m3u8?token=master");
const aliasDash = response.resources.find(item => item.url === "https://course.example.com/static/alias-manifest.mpd?token=dash");
const aliasBackupVideo = response.resources.find(item => item.url === "https://course.example.com/static/alias-backup.mp4?token=backup");
const aliasDownloadVideo = response.resources.find(item => item.url === "https://course.example.com/static/alias-download.mp4?token=download");
const video = response.resources.find(item => item.url === "https://cdn.example.com/static/lesson.mp4?token=script");
const flv = response.resources.find(item => item.url === "https://cdn.example.com/static/live.flv?token=script");
const plainHls = response.resources.find(item => item.url === "https://cdn.example.com/static/plain-master.m3u8?token=plain&uid=1");
const doubleHls = response.resources.find(item => item.url === "https://cdn.example.com/static/double/master.m3u8?token=double&uid=2");
const doubleNakedVideo = response.resources.find(item => item.url === "https://cdn.example.com/static/double/naked.mp4?token=naked-double");
const mixedVideo = response.resources.find(item => item.url === "https://cdn.example.com/static/mixed/lesson.mp4?token=mixed");
const jsEscapedHls = response.resources.find(item => item.url === "https://cdn.example.com/static/escaped/master.m3u8?token=js&uid=7");
const jsEscapedVideo = response.resources.find(item => item.url === "https://cdn.example.com/static/escaped/lesson.mp4?sig=ok");
const jsEscapedPayloadHls = response.resources.find(item => item.url === "https://cdn.example.com/static/escaped/payload.m3u8?token=payload");
const nestedMediaKeyHls = response.resources.find(item => item.url === "https://cdn.example.com/static/nested-key/master.m3u8?token=wrapped");
const splitBaseHls = response.resources.find(item => item.url === "https://cdn.example.com/static/split/course/master.m3u8?token=split-static");
const apiPlayEndpoint = response.resources.find(item => item.url === "https://course.example.com/api/play?id=json-array&token=abc");
const ananasEndpoint = response.resources.find(item => item.url === "https://course.example.com/ananas/status/objectid-123?flag=normal");
const vodEndpoint = response.resources.find(item => item.url === "https://media.example.com/vod/lesson?id=noext");
const definitionEndpoint = response.resources.find(item => item.url === "https://course.example.com/api/play?id=definition-hd");
const qualityPlayEndpoint = response.resources.find(item => item.url === "https://course.example.com/api/play?id=quality-play");
const formatVideo = response.resources.find(item => item.url === "https://course.example.com/static/formats/lesson.mp4?token=format");
const renditionHls = response.resources.find(item => item.url === "https://course.example.com/static/renditions/master.m3u8?token=rendition");
const hlsSegment = response.resources.find(item => item.url === "https://cdn.example.com/static/hls/segment-001.ts?token=seg");
const onclickHls = response.resources.find(item => item.url === "https://cdn.example.com/static/onclick-master.m3u8?token=click");
const paramVideo = response.resources.find(item => item.url === "https://cdn.example.com/static/param-lesson.mp4?token=param");
const lazyPathEndpoint = response.resources.find(item => item.url === "https://course.example.com/ananas/status/objectid-lazy?flag=normal");
const lazyUriEndpoint = response.resources.find(item => item.url === "https://course.example.com/vod/play?id=uri-lazy&token=ok");
const ordinaryPathEndpoint = response.resources.find(item => item.url === "https://course.example.com/ordinary/page");
const plainAttrVideo = response.resources.find(item => item.url === "https://course.example.com/static/plain-attr.mp4?token=attr-plain");
const nakedAttrHls = response.resources.find(item => item.url === "https://course.example.com/static/naked-master.m3u8?token=naked");
const vendorAttrHls = response.resources.find(item => item.url === "https://cdn.example.com/static/vendor/master.m3u8?token=vendor");
const preloadVideoHint = response.resources.find(item => item.url === "https://course.example.com/opaque/video-stream?id=preload");
const preloadHlsHint = response.resources.find(item => item.url === "https://course.example.com/opaque/playlist?id=typed-hls");
const prefetchPlayHint = response.resources.find(item => item.url === "https://course.example.com/api/play?id=prefetch");
const ogVideoHint = response.resources.find(item => item.url === "https://course.example.com/opaque/og-stream?id=meta");
const html5VideoHint = response.resources.find(item => item.url === "https://course.example.com/api/play?id=html5&token=abc");
const html5HlsHint = response.resources.find(item => item.url === "https://course.example.com/opaque/html5-hls?id=42");
const html5DashHint = response.resources.find(item => item.url === "https://course.example.com/opaque/html5-dash?id=42");
const html5TrackHint = response.resources.find(item => item.url === "https://course.example.com/caption?id=html5");
const performancePlayHint = response.resources.find(item => item.url === "https://course.example.com/api/play?id=perf");
const performanceChaoxingHint = response.resources.find(item => item.url === "https://mooc1.chaoxing.com/ananas/status/objectid-perf?flag=normal");
const unrelatedPerformanceHint = response.resources.find(item => item.url === "https://course.example.com/lesson-data?id=not-media");
const plainScriptHls = response.resources.find(item => item.url === "https://cdn.example.com/static/plain-url.m3u8?token=script-plain");
const iframeSrcdocHls = response.resources.find(item => item.url === "https://cdn.example.com/static/iframe-srcdoc/master.m3u8?token=srcdoc");
const iframeDocumentVideo = response.resources.find(item => item.url === "https://cdn.example.com/static/iframe-doc/lesson.mp4?token=doc");
const malformedEncodedUrls = response.resources.filter(item => /\/https%3A%2F%2F/i.test(item.url));

assert.ok(pageUrlHls, "expected current page URL query to expose encoded HLS URL");
assert.equal(pageUrlHls.kind, "hls");
assert.equal(pageUrlHls.source, "locationHint");
assert.match(pageUrlHls.label, /current page URL query objectid param/);

assert.ok(pageUrlPackedVideo, "expected current page URL query parameter JSON to expose video URL");
assert.equal(pageUrlPackedVideo.kind, "video");
assert.equal(pageUrlPackedVideo.source, "locationHint");
assert.match(pageUrlPackedVideo.label, /current page URL query player param/);

assert.ok(pageHashHls, "expected current page URL hash parameter JSON to expose split-base HLS URL");
assert.equal(pageHashHls.kind, "hls");
assert.equal(pageHashHls.source, "locationHint");
assert.match(pageHashHls.label, /current page URL hash payload param/);

assert.ok(hls, "expected data-play-url media hint to expose encoded HLS URL");
assert.equal(hls.kind, "hls");
assert.equal(hls.source, "domHint");
assert.match(hls.label, /data-play-url/);

assert.ok(dash, "expected base64 data-video-url media hint to expose DASH manifest");
assert.equal(dash.kind, "dash");
assert.equal(dash.source, "domHint");
assert.match(dash.label, /data-video-url/);

assert.ok(aliasPlayVideo, "expected data-playurl alias to expose direct video");
assert.equal(aliasPlayVideo.kind, "video");
assert.equal(aliasPlayVideo.source, "domHint");
assert.match(aliasPlayVideo.label, /data-playurl/);

assert.ok(aliasMasterHls, "expected data-master-url alias to expose HLS manifest");
assert.equal(aliasMasterHls.kind, "hls");
assert.equal(aliasMasterHls.source, "domHint");
assert.match(aliasMasterHls.label, /data-master-url/);

assert.ok(aliasDash, "expected data-dash-url alias to expose DASH manifest");
assert.equal(aliasDash.kind, "dash");
assert.equal(aliasDash.source, "domHint");
assert.match(aliasDash.label, /data-dash-url/);

assert.ok(aliasBackupVideo, "expected data-backup-url alias to expose backup video");
assert.equal(aliasBackupVideo.kind, "video");
assert.equal(aliasBackupVideo.source, "domHint");
assert.match(aliasBackupVideo.label, /data-backup-url/);

assert.ok(aliasDownloadVideo, "expected data-download-url alias to expose downloadable video");
assert.equal(aliasDownloadVideo.kind, "video");
assert.equal(aliasDownloadVideo.source, "domHint");
assert.match(aliasDownloadVideo.label, /data-download-url/);

assert.ok(video, "expected inline script media hint to expose encoded mp4 URL");
assert.equal(video.kind, "video");
assert.equal(video.source, "scriptHint");
assert.match(video.label, /videoUrl/);

assert.ok(flv, "expected inline script media hint to expose FLV URL");
assert.equal(flv.kind, "video");
assert.equal(flv.source, "scriptHint");
assert.match(flv.label, /flvUrl/);

assert.ok(plainHls, "expected inline script encoded URL scan to expose HLS URL without a media field name");
assert.equal(plainHls.kind, "hls");
assert.equal(plainHls.source, "scriptHint");
assert.match(plainHls.label, /encoded url/);

assert.ok(doubleHls, "expected DOM media hint to expose double-encoded HLS URL");
assert.equal(doubleHls.kind, "hls");
assert.equal(doubleHls.source, "domHint");
assert.match(doubleHls.label, /data-hls-url/);

assert.ok(doubleNakedVideo, "expected inline script encoded URL scan to expose double-encoded mp4 URL without a media field name");
assert.equal(doubleNakedVideo.kind, "video");
assert.equal(doubleNakedVideo.source, "scriptHint");
assert.match(doubleNakedVideo.label, /encoded url/);

assert.ok(mixedVideo, "expected inline script encoded URL scan to expose mixed-encoded mp4 URL");
assert.equal(mixedVideo.kind, "video");
assert.equal(mixedVideo.source, "scriptHint");
assert.match(mixedVideo.label, /encoded url/);

assert.ok(jsEscapedHls, "expected inline script field scan to decode JS-escaped HLS URL");
assert.equal(jsEscapedHls.kind, "hls");
assert.equal(jsEscapedHls.source, "scriptHint");
assert.match(jsEscapedHls.label, /hls/);

assert.ok(jsEscapedVideo, "expected inline script field scan to decode JS-escaped mp4 URL");
assert.equal(jsEscapedVideo.kind, "video");
assert.equal(jsEscapedVideo.source, "scriptHint");
assert.match(jsEscapedVideo.label, /videoUrl/);

assert.ok(jsEscapedPayloadHls, "expected inline script text scan to decode JS-escaped HLS URL without media field name");
assert.equal(jsEscapedPayloadHls.kind, "hls");
assert.equal(jsEscapedPayloadHls.source, "scriptHint");
assert.match(jsEscapedPayloadHls.label, /script media url/);

assert.ok(nestedMediaKeyHls, "expected nested JSON inside a media-named script field to expose HLS URL");
assert.equal(nestedMediaKeyHls.kind, "hls");
assert.equal(nestedMediaKeyHls.source, "scriptHint");
assert.match(nestedMediaKeyHls.label, /nested/);

assert.ok(splitBaseHls, "expected nested JSON base URL and media path fields to expose HLS URL");
assert.equal(splitBaseHls.kind, "hls");
assert.equal(splitBaseHls.source, "scriptHint");
assert.match(splitBaseHls.label, /json combined/);

assert.ok(apiPlayEndpoint, "expected media-named source array to expose extensionless play endpoint");
assert.equal(apiPlayEndpoint.kind, "video");
assert.equal(apiPlayEndpoint.source, "scriptHint");
assert.match(apiPlayEndpoint.label, /(file|sources container)/);

assert.ok(ananasEndpoint, "expected media-named source array to expose Chaoxing-style ananas endpoint");
assert.equal(ananasEndpoint.kind, "video");
assert.equal(ananasEndpoint.source, "scriptHint");
assert.match(ananasEndpoint.label, /(url|sources container)/);

assert.ok(vodEndpoint, "expected media-named stream array to expose extensionless VOD endpoint");
assert.equal(vodEndpoint.kind, "video");
assert.equal(vodEndpoint.source, "scriptHint");
assert.match(vodEndpoint.label, /(streams|coursePlayer) container/);

assert.ok(definitionEndpoint, "expected definitions/address to expose extensionless play endpoint");
assert.equal(definitionEndpoint.kind, "video");
assert.equal(definitionEndpoint.source, "scriptHint");

assert.ok(qualityPlayEndpoint, "expected qualities/play to expose extensionless play endpoint");
assert.equal(qualityPlayEndpoint.kind, "video");
assert.equal(qualityPlayEndpoint.source, "scriptHint");

assert.ok(formatVideo, "expected formats/file to expose direct video");
assert.equal(formatVideo.kind, "video");
assert.equal(formatVideo.source, "scriptHint");

assert.ok(renditionHls, "expected renditions/src to expose HLS manifest");
assert.equal(renditionHls.kind, "hls");
assert.equal(renditionHls.source, "scriptHint");

assert.ok(hlsSegment, "expected inline script media scan to expose HLS segment URL");
assert.equal(hlsSegment.kind, "fragment");
assert.equal(hlsSegment.source, "scriptHint");
assert.match(hlsSegment.label, /(segments container|script media url)/);

assert.ok(onclickHls, "expected onclick handler scan to expose embedded encoded HLS URL");
assert.equal(onclickHls.kind, "hls");
assert.equal(onclickHls.source, "domHint");
assert.match(onclickHls.label, /onclick encoded url/);

assert.ok(paramVideo, "expected data-params scan to expose embedded encoded mp4 URL");
assert.equal(paramVideo.kind, "video");
assert.equal(paramVideo.source, "domHint");
assert.match(paramVideo.label, /data-params/);

assert.ok(lazyPathEndpoint, "expected lazy data-path playback endpoint to be detected");
assert.equal(lazyPathEndpoint.kind, "video");
assert.equal(lazyPathEndpoint.source, "domHint");
assert.match(lazyPathEndpoint.label, /data-path/);

assert.ok(lazyUriEndpoint, "expected lazy data-uri playback endpoint to be detected");
assert.equal(lazyUriEndpoint.kind, "video");
assert.equal(lazyUriEndpoint.source, "domHint");
assert.match(lazyUriEndpoint.label, /data-uri/);

assert.equal(ordinaryPathEndpoint, undefined, "expected ordinary data-path navigation value to stay out of media candidates");

assert.ok(plainAttrVideo, "expected data-config scan to expose embedded plain relative mp4 URL");
assert.equal(plainAttrVideo.kind, "video");
assert.equal(plainAttrVideo.source, "domHint");
assert.match(plainAttrVideo.label, /data-config media url/);

assert.ok(nakedAttrHls, "expected data-options scan to trim trailing JS punctuation from plain HLS URL");
assert.equal(nakedAttrHls.kind, "hls");
assert.equal(nakedAttrHls.source, "domHint");
assert.match(nakedAttrHls.label, /data-options/);

assert.ok(vendorAttrHls, "expected non-standard player attribute JSON to expose HLS URL");
assert.equal(vendorAttrHls.kind, "hls");
assert.equal(vendorAttrHls.source, "domHint");
assert.match(vendorAttrHls.label, /vendor-player-json/);

assert.ok(preloadVideoHint, "expected link preload as=video to expose extensionless media URL");
assert.equal(preloadVideoHint.kind, "video");
assert.equal(preloadVideoHint.source, "domHint");
assert.match(preloadVideoHint.label, /link preload as=video/);

assert.ok(preloadHlsHint, "expected typed link preload to expose extensionless HLS URL");
assert.equal(preloadHlsHint.kind, "hls");
assert.equal(preloadHlsHint.source, "domHint");
assert.match(preloadHlsHint.label, /application\/vnd\.apple\.mpegurl/);

assert.ok(prefetchPlayHint, "expected link prefetch as=fetch play API to expose direct-response candidate");
assert.equal(prefetchPlayHint.kind, "video");
assert.equal(prefetchPlayHint.source, "domHint");
assert.match(prefetchPlayHint.label, /link prefetch as=fetch/);

assert.ok(ogVideoHint, "expected og:video meta hint to expose extensionless media URL");
assert.equal(ogVideoHint.kind, "video");
assert.equal(ogVideoHint.source, "domHint");
assert.match(ogVideoHint.label, /og:video/);

assert.ok(html5VideoHint, "expected HTML5 video src to expose extensionless media URL");
assert.equal(html5VideoHint.kind, "video");
assert.ok(["activeVideo", "domHint"].includes(html5VideoHint.source));
assert.match(html5VideoHint.label, /当前视频|video src/);

assert.ok(html5HlsHint, "expected typed HTML5 source src to expose extensionless HLS URL");
assert.equal(html5HlsHint.kind, "hls");
assert.ok(["dom", "domHint"].includes(html5HlsHint.source));
assert.match(html5HlsHint.label, /application\/vnd\.apple\.mpegurl|video source/);

assert.ok(html5DashHint, "expected typed HTML5 source data-src to expose extensionless DASH URL");
assert.equal(html5DashHint.kind, "dash");
assert.ok(["dom", "domHint"].includes(html5DashHint.source));
assert.match(html5DashHint.label, /application\/dash\+xml|source/);

assert.ok(html5TrackHint, "expected HTML5 track src to expose extensionless subtitle URL");
assert.equal(html5TrackHint.kind, "subtitle");
assert.ok(["subtitleTrack", "domHint"].includes(html5TrackHint.source));
assert.match(html5TrackHint.label, /track subtitles|subtitles/);

assert.ok(performancePlayHint, "expected fetch performance play endpoint to enter direct-preflight candidates");
assert.equal(performancePlayHint.kind, "video");
assert.equal(performancePlayHint.source, "performance");
assert.equal(performancePlayHint.request_type, "fetch");
assert.equal(performancePlayHint.content_length, 2048);
assert.ok(performanceChaoxingHint, "expected Chaoxing ananas performance endpoint to enter direct-preflight candidates");
assert.equal(performanceChaoxingHint.kind, "video");
assert.equal(performanceChaoxingHint.source, "performance");
assert.equal(performanceChaoxingHint.request_type, "xmlhttprequest");
assert.equal(performanceChaoxingHint.content_length, 4096);
assert.equal(unrelatedPerformanceHint, undefined, "expected unrelated fetch performance entry to stay out of media candidates");

assert.ok(plainScriptHls, "expected inline script URL scan to expose plain HLS URL without a media field name");
assert.equal(plainScriptHls.kind, "hls");
assert.equal(plainScriptHls.source, "scriptHint");
assert.match(plainScriptHls.label, /script media url/);

assert.ok(iframeSrcdocHls, "expected iframe srcdoc scan to expose HLS URL");
assert.equal(iframeSrcdocHls.kind, "hls");
assert.equal(iframeSrcdocHls.source, "iframeHint");
assert.match(iframeSrcdocHls.label, /Inline player srcdoc hls/);

assert.ok(iframeDocumentVideo, "expected same-origin iframe document scan to expose mp4 URL");
assert.equal(iframeDocumentVideo.kind, "video");
assert.equal(iframeDocumentVideo.source, "iframeHint");
assert.match(iframeDocumentVideo.label, /Same origin player document videoUrl/);

assert.equal(malformedEncodedUrls.length, 0, "expected encoded absolute media URLs to normalize before URL resolution");
