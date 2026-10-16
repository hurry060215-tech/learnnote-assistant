// Synthetic inputs shared by the pre-extraction snapshot and the current domains.
export const fixturePageUrl = "https://course.example.test/lesson?chapterId=2&utm_source=fixture#seek";
export const fixturePartition = { topLevelSite: "https://course.example.test", hasCrossSiteAncestor: true };
export function cookiePort() {
  return {
    async getPartitionKey({ frameId }) {
      if (frameId === 9) throw Error("inaccessible fixture frame");
      return frameId === 2 ? fixturePartition : { topLevelSite: fixturePartition.topLevelSite };
    },
    async getAll(details) {
      if (details.domain) return [];
      return [{ name: "session", value: details.partitionKey ? "synthetic-partition" : "synthetic-plain", domain: ".example.test", path: "/" }];
    }
  };
}
export async function domainSnapshot({ identity, request, cookies, hints }) {
  const tab = { id: 7, url: fixturePageUrl, title: "Readable lesson" };
  const page = { page_url: fixturePageUrl, title: "????", active_video: { src: "https://media.example.test/main.mp4?token=synthetic&quality=hd", frame_id: 2 }, frames: [{ frame_id: 9, page_url: "https://frame.example.test/player" }] };
  const resources = [{ url: page.active_video.src, score: 90, kind: "video", frame_id: 2, request_headers: { Referer: fixturePageUrl } }];
  const source = identity.buildSourceIdentity(tab, page, resources, 1700000000000);
  const changedToken = identity.buildSourceIdentity(tab, { ...page, active_video: { src: page.active_video.src.replace("synthetic", "rotated") } }, resources, 1700000000000);
  const partitionKeys = await cookies.cookiePartitionKeysForContext(page, tab, resources);
  const cookieUrls = cookies.cookieUrlsForContext(page, tab, resources);
  const selectedCookies = await cookies.cookiesForUrls(cookieUrls, partitionKeys);
  return {
    source,
    sourceMatch: identity.sourceIdentityMatches(source, changedToken),
    sourceTabMismatch: identity.sourceIdentityMatches(source, { ...source, tab_id: 8 }),
    titleFallback: identity.bestPageTitle("???", "\ufffd\ufffd\ufffd", " Lesson "),
    headers: request.normalizeRequestHeaders([{ name: "Referer", value: fixturePageUrl }, { name: "authorization", value: "synthetic\r\ncredential" }, { name: "Cookie", value: "excluded" }, { name: "Sec-CH-UA", value: "fixture" }]),
    persistedHeaders: request.safePersistedRequestHeaders({ Authorization: "synthetic", Cookie: "synthetic", "Proxy-Authorization": "synthetic", Referer: fixturePageUrl, Custom: " clean\r\nvalue " }),
    redirectedHeaders: ["https://media.example.test/next.mp4", "https://other.example.test/next.mp4", "https://user@media.example.test/next.mp4", "https://media.example.test\\evil"].map(url => request.requestHeadersForUrl({ url: resources[0].url, request_headers: { Authorization: "synthetic", Range: "bytes=0-" } }, url)),
    bodies: [request.requestBodyFromFormData({ field: ["first", "second"], empty: null }), request.requestBodyFromRaw([{ bytes: new TextEncoder().encode(" fixture text ").buffer }]), request.requestBodyFromRaw([{ bytes: new Uint8Array([0, 1]).buffer }])],
    persistedBodies: [
      request.safePersistedRequestBody({ method: "POST", kind: "video", request_body: { type: "text", content: "synthetic=1" } }),
      request.safePersistedRequestBody({ method: "GET", kind: "video", request_body: { type: "text", content: "synthetic=1" } }),
      request.safePersistedRequestBody({ request_body: { type: "dropped", reason: "too_large_or_binary" } })
    ],
    responseHeaders: request.responseHeadersObject([{ name: "Location", value: " /final.mp4\r\n " }, { name: "Set-Cookie", value: "excluded" }, { name: "Content-Length", value: "42" }]),
    resolvedUrl: request.responseResolvedUrl("https://media.example.test/stream", { location: "../final.mp4" }),
    partitionKeys, cookieUrls, selectedCookies,
    cookieSummary: cookies.cookieContextSummary(selectedCookies, cookieUrls, partitionKeys),
    lookupDetails: cookies.cookieLookupDetailsForUrls(["blob:https://media.example.test/id", "file:///excluded", "https://127.0.0.1/video"], [fixturePartition]),
    media: ["blob:https://course.example.test/id", "cover.jpg@320w.avi", "/captions?id=1", "https://media.example.test/part.m4s"].map(url => hints.classify(url)),
    decoded: hints.decodedValues("https%253A%252F%252Fmedia.example.test%252Fmain.mp4%253Fid%253D2"),
    escaped: hints.decodeJsStringEscapes(String.raw`https:\/\/media.example.test\/main.mp4\u003fid\x3d2`),
    baseUrls: hints.staticJsonBaseUrls({ host: "cdn.example.test", basepath: "/course/", unrelated: "ignore" }),
    split: hints.staticSplitCandidateValues("main%252Emp4"),
    relative: hints.absoluteUrl("../media/main.mp4"),
    hints: [hints.mimeFromHint("audio"), hints.looksLikePlaybackEndpointValue("/api/play?id=1", "video"), hints.looksLikeMediaValue("image.jpg", "video")]
  };
}
