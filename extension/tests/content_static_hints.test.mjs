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

const player = new FakeElement("div", {
  "data-play-url": "https%3A%2F%2Fcdn.example.com%2Fstatic%2Fmaster.m3u8%3Ftoken%3Dattr"
});
const packedPlayer = new FakeElement("div", {
  "data-video-url": packedDash
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
const segmentScript = new FakeElement("script", {
  textContent: "window.__segments=['https://cdn.example.com/static/hls/segment-001.ts?token=seg'];"
});
const onclickPlayer = new FakeElement("button", {
  onclick: "openPlayer('https%3A%2F%2Fcdn.example.com%2Fstatic%2Fonclick-master.m3u8%3Ftoken%3Dclick')"
});
const paramPlayer = new FakeElement("div", {
  "data-params": "objectid=ignored&play=https%3A%2F%2Fcdn.example.com%2Fstatic%2Fparam-lesson.mp4%3Ftoken%3Dparam"
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
const plainUrlScript = new FakeElement("script", {
  textContent: "window.__payload='https://cdn.example.com/static/plain-url.m3u8?token=script-plain';"
});
const html = new FakeElement("html", {}, [player, packedPlayer, doubleEncodedPlayer, onclickPlayer, paramPlayer, configPlayer, nakedPlayer, vendorPlayer, preloadVideo, preloadHls, prefetchPlayApi, ogVideo, script, plainEncodedScript, plainDoubleEncodedScript, mixedEncodedScript, jsEscapedScript, jsEscapedPayloadScript, segmentScript, plainUrlScript]);

let messageListener = null;
const context = {
  console,
  URL,
  Node: { ELEMENT_NODE: 1 },
  location: { href: `https://course.example.com/lesson?objectid=${pageUrlEncodedHls}` },
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
      return [];
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
const dash = response.resources.find(item => item.url === "https://cdn.example.com/static/manifest.mpd?token=b64");
const video = response.resources.find(item => item.url === "https://cdn.example.com/static/lesson.mp4?token=script");
const flv = response.resources.find(item => item.url === "https://cdn.example.com/static/live.flv?token=script");
const plainHls = response.resources.find(item => item.url === "https://cdn.example.com/static/plain-master.m3u8?token=plain&uid=1");
const doubleHls = response.resources.find(item => item.url === "https://cdn.example.com/static/double/master.m3u8?token=double&uid=2");
const doubleNakedVideo = response.resources.find(item => item.url === "https://cdn.example.com/static/double/naked.mp4?token=naked-double");
const mixedVideo = response.resources.find(item => item.url === "https://cdn.example.com/static/mixed/lesson.mp4?token=mixed");
const jsEscapedHls = response.resources.find(item => item.url === "https://cdn.example.com/static/escaped/master.m3u8?token=js&uid=7");
const jsEscapedVideo = response.resources.find(item => item.url === "https://cdn.example.com/static/escaped/lesson.mp4?sig=ok");
const jsEscapedPayloadHls = response.resources.find(item => item.url === "https://cdn.example.com/static/escaped/payload.m3u8?token=payload");
const hlsSegment = response.resources.find(item => item.url === "https://cdn.example.com/static/hls/segment-001.ts?token=seg");
const onclickHls = response.resources.find(item => item.url === "https://cdn.example.com/static/onclick-master.m3u8?token=click");
const paramVideo = response.resources.find(item => item.url === "https://cdn.example.com/static/param-lesson.mp4?token=param");
const plainAttrVideo = response.resources.find(item => item.url === "https://course.example.com/static/plain-attr.mp4?token=attr-plain");
const nakedAttrHls = response.resources.find(item => item.url === "https://course.example.com/static/naked-master.m3u8?token=naked");
const vendorAttrHls = response.resources.find(item => item.url === "https://cdn.example.com/static/vendor/master.m3u8?token=vendor");
const preloadVideoHint = response.resources.find(item => item.url === "https://course.example.com/opaque/video-stream?id=preload");
const preloadHlsHint = response.resources.find(item => item.url === "https://course.example.com/opaque/playlist?id=typed-hls");
const prefetchPlayHint = response.resources.find(item => item.url === "https://course.example.com/api/play?id=prefetch");
const ogVideoHint = response.resources.find(item => item.url === "https://course.example.com/opaque/og-stream?id=meta");
const plainScriptHls = response.resources.find(item => item.url === "https://cdn.example.com/static/plain-url.m3u8?token=script-plain");
const malformedEncodedUrls = response.resources.filter(item => /\/https%3A%2F%2F/i.test(item.url));

assert.ok(pageUrlHls, "expected current page URL query to expose encoded HLS URL");
assert.equal(pageUrlHls.kind, "hls");
assert.equal(pageUrlHls.source, "locationHint");
assert.match(pageUrlHls.label, /current page URL encoded url/);

assert.ok(hls, "expected data-play-url media hint to expose encoded HLS URL");
assert.equal(hls.kind, "hls");
assert.equal(hls.source, "domHint");
assert.match(hls.label, /data-play-url/);

assert.ok(dash, "expected base64 data-video-url media hint to expose DASH manifest");
assert.equal(dash.kind, "dash");
assert.equal(dash.source, "domHint");
assert.match(dash.label, /data-video-url/);

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

assert.ok(hlsSegment, "expected inline script media scan to expose HLS segment URL");
assert.equal(hlsSegment.kind, "fragment");
assert.equal(hlsSegment.source, "scriptHint");
assert.match(hlsSegment.label, /script media url/);

assert.ok(onclickHls, "expected onclick handler scan to expose embedded encoded HLS URL");
assert.equal(onclickHls.kind, "hls");
assert.equal(onclickHls.source, "domHint");
assert.match(onclickHls.label, /onclick encoded url/);

assert.ok(paramVideo, "expected data-params scan to expose embedded encoded mp4 URL");
assert.equal(paramVideo.kind, "video");
assert.equal(paramVideo.source, "domHint");
assert.match(paramVideo.label, /data-params/);

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

assert.ok(plainScriptHls, "expected inline script URL scan to expose plain HLS URL without a media field name");
assert.equal(plainScriptHls.kind, "hls");
assert.equal(plainScriptHls.source, "scriptHint");
assert.match(plainScriptHls.label, /script media url/);

assert.equal(malformedEncodedUrls.length, 0, "expected encoded absolute media URLs to normalize before URL resolution");
