const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv|m3u8|mpd)(\?|#|$)/i;
const FRAGMENT_RE = /\.(m4s|ts)(\?|#|$)/i;

function classify(url, mime = "") {
  const lower = String(url || "").toLowerCase();
  const type = String(mime || "").toLowerCase();
  if (lower.startsWith("blob:")) return "blob";
  if (type.includes("mpegurl") || lower.includes(".m3u8")) return "hls";
  if (type.includes("dash+xml") || lower.includes(".mpd")) return "dash";
  if (type.includes("video/") || MEDIA_RE.test(lower)) return "video";
  if (FRAGMENT_RE.test(lower)) return "fragment";
  return "unknown";
}

function score(url, mime, source) {
  const kind = classify(url, mime);
  let value = 0;
  if (kind === "hls" || kind === "dash") value += 95;
  else if (kind === "video") value += 85;
  else if (kind === "fragment") value += 15;
  else if (kind === "blob") value += 5;
  if (source === "dom") value += 8;
  if (/chaoxing|xuexitong/i.test(url)) value += 8;
  return Math.min(value, 100);
}

function resource(url, source, label, mime = "") {
  if (!url) return null;
  const absolute = url.startsWith("blob:") ? url : new URL(url, location.href).href;
  const kind = classify(absolute, mime);
  return { url: absolute, source, kind, mime, label, score: score(absolute, mime, source) };
}

function collectDomResources() {
  const resources = [];
  for (const video of document.querySelectorAll("video")) {
    resources.push(resource(video.currentSrc || video.src, "dom", "video.currentSrc"));
    for (const source of video.querySelectorAll("source")) {
      resources.push(resource(source.src, "dom", "video source", source.type || ""));
    }
  }
  for (const source of document.querySelectorAll("source[src]")) {
    resources.push(resource(source.src, "dom", "source", source.type || ""));
  }
  for (const iframe of document.querySelectorAll("iframe[src]")) {
    if (/chaoxing|xuexitong|video|player|course/i.test(iframe.src)) {
      resources.push(resource(iframe.src, "dom", "iframe"));
    }
  }
  return resources.filter(Boolean);
}

function collectPerformanceResources() {
  const resources = [];
  for (const entry of performance.getEntriesByType("resource")) {
    const name = entry.name || "";
    if (MEDIA_RE.test(name) || FRAGMENT_RE.test(name) || /m3u8|mpd|video|media/i.test(name)) {
      resources.push(resource(name, "performance", "performance"));
    }
  }
  return resources.filter(Boolean);
}

function collectCourseText() {
  const candidates = [
    ...document.querySelectorAll("h1,h2,h3,.course-title,.chapter-title,.ans-job-icon,.title,.name")
  ];
  const headings = candidates.map(el => el.textContent?.trim()).filter(Boolean).slice(0, 40).join("\n");
  const body = document.body?.innerText || "";
  return [headings, body].filter(Boolean).join("\n\n").slice(0, 60000);
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "collect-page-data") return;
  const all = [...collectDomResources(), ...collectPerformanceResources()];
  const byUrl = new Map();
  for (const item of all) {
    const previous = byUrl.get(item.url);
    if (!previous || item.score > previous.score) byUrl.set(item.url, item);
  }
  sendResponse({
    title: document.title,
    page_url: location.href,
    page_text: collectCourseText(),
    resources: [...byUrl.values()].sort((a, b) => b.score - a.score).slice(0, 30)
  });
});
