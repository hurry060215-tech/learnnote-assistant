const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv|m3u8|mpd)(\?|#|$)/i;
const FRAGMENT_RE = /\.(m4s|ts)(\?|#|$)/i;
const SUBTITLE_RE = /\.(vtt|srt|ass|ssa)(\?|#|$)/i;

function classify(url, mime = "") {
  const lower = String(url || "").toLowerCase();
  const type = String(mime || "").toLowerCase();
  if (lower.startsWith("blob:")) return "blob";
  if (type.includes("mpegurl") || lower.includes(".m3u8")) return "hls";
  if (type.includes("dash+xml") || lower.includes(".mpd")) return "dash";
  if (type.includes("video/") || MEDIA_RE.test(lower)) return "video";
  if (type.includes("text/vtt") || type.includes("subrip") || SUBTITLE_RE.test(lower)) return "subtitle";
  if (FRAGMENT_RE.test(lower)) return "fragment";
  return "unknown";
}

function score(url, mime, source) {
  const kind = classify(url, mime);
  let value = 0;
  if (kind === "hls" || kind === "dash") value += 95;
  else if (kind === "video") value += 85;
  else if (kind === "fragment") value += 15;
  else if (kind === "subtitle") value += 60;
  else if (kind === "blob") value += 5;
  if (source === "dom") value += 8;
  if (source === "activeVideo") value += 16;
  if (/chaoxing|xuexitong/i.test(url)) value += 8;
  return Math.min(value, 100);
}

function absoluteUrl(url) {
  if (!url) return "";
  if (url.startsWith("blob:")) return url;
  try {
    return new URL(url, location.href).href;
  } catch {
    return "";
  }
}

function resource(url, source, label, mime = "", video = null, isMainVideo = false) {
  const absolute = absoluteUrl(url);
  if (!absolute) return null;
  const kind = classify(absolute, mime);
  return {
    url: absolute,
    source,
    kind,
    mime,
    label,
    score: score(absolute, mime, source),
    is_main_video: isMainVideo,
    current_time: video ? Number(video.currentTime || 0) : null,
    duration: video && Number.isFinite(video.duration) ? Number(video.duration || 0) : null,
    width: video ? Number(video.videoWidth || video.clientWidth || 0) : null,
    height: video ? Number(video.videoHeight || video.clientHeight || 0) : null
  };
}

function collectVideos() {
  return [...document.querySelectorAll("video")].map((video, index) => ({ video, index }));
}

function pickMainVideo(videos = collectVideos()) {
  const playing = videos.find(({ video }) => !video.paused && !video.ended && video.readyState >= 2);
  if (playing) return playing;
  return videos
    .filter(({ video }) => video.currentSrc || video.src || video.querySelector("source[src]"))
    .sort((a, b) => {
      const areaA = Number(a.video.videoWidth || a.video.clientWidth || 0) * Number(a.video.videoHeight || a.video.clientHeight || 0);
      const areaB = Number(b.video.videoWidth || b.video.clientWidth || 0) * Number(b.video.videoHeight || b.video.clientHeight || 0);
      return areaB - areaA;
    })[0] || null;
}

function activeVideoInfo() {
  const videos = collectVideos();
  const withSource = pickMainVideo(videos);
  if (!withSource) return null;
  const { video, index } = withSource;
  return {
    src: absoluteUrl(video.currentSrc || video.src),
    current_time: Number(video.currentTime || 0),
    duration: Number.isFinite(video.duration) ? Number(video.duration || 0) : 0,
    paused: Boolean(video.paused),
    width: Number(video.videoWidth || video.clientWidth || 0),
    height: Number(video.videoHeight || video.clientHeight || 0),
    frame_id: 0,
    label: `video#${index + 1}`
  };
}

function collectDomResources() {
  const resources = [];
  const videos = collectVideos();
  const main = pickMainVideo(videos);
  for (const { video, index } of videos) {
    const isMain = main?.video === video;
    resources.push(resource(video.currentSrc || video.src, "activeVideo", `当前视频 #${index + 1}`, video.type || "", video, isMain));
    for (const source of video.querySelectorAll("source")) {
      resources.push(resource(source.src, "dom", `video source #${index + 1}`, source.type || "", video, isMain));
    }
    for (const track of video.querySelectorAll("track[src]")) {
      const label = [track.kind || "subtitle", track.srclang || "", track.label || ""].filter(Boolean).join(" ");
      resources.push(resource(track.src, "subtitleTrack", label || `subtitle #${index + 1}`, "text/vtt", video, isMain));
    }
  }
  for (const source of document.querySelectorAll("source[src]")) {
    resources.push(resource(source.src, "dom", "source", source.type || ""));
  }
  for (const track of document.querySelectorAll("track[src]")) {
    const label = [track.kind || "subtitle", track.srclang || "", track.label || ""].filter(Boolean).join(" ");
    resources.push(resource(track.src, "subtitleTrack", label || "subtitle", "text/vtt"));
  }
  for (const iframe of document.querySelectorAll("iframe[src]")) {
    if (/chaoxing|xuexitong|video|player|course|m3u8|mpd/i.test(iframe.src)) {
      resources.push(resource(iframe.src, "dom", "iframe"));
    }
  }
  return resources.filter(Boolean);
}

function collectPerformanceResources() {
  const resources = [];
  for (const entry of performance.getEntriesByType("resource")) {
    const name = entry.name || "";
    if (MEDIA_RE.test(name) || FRAGMENT_RE.test(name) || SUBTITLE_RE.test(name) || /m3u8|mpd|video|media|subtitle|caption/i.test(name)) {
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

function collectPageData() {
  const all = [...collectDomResources(), ...collectPerformanceResources()];
  const byUrl = new Map();
  for (const item of all) {
    const previous = byUrl.get(item.url);
    if (!previous || item.score > previous.score) byUrl.set(item.url, item);
  }
  return {
    title: document.title,
    page_url: location.href,
    page_text: collectCourseText(),
    active_video: activeVideoInfo(),
    resources: [...byUrl.values()].sort((a, b) => b.score - a.score).slice(0, 30)
  };
}

function pushDetectedMedia() {
  const data = collectPageData();
  if (!data.resources.length && !data.active_video) return;
  chrome.runtime.sendMessage({ type: "page-media-detected", page: data }).catch(() => {});
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "collect-page-data") return;
  sendResponse(collectPageData());
});

for (const { video } of collectVideos()) {
  video.addEventListener("play", pushDetectedMedia, { passive: true });
  video.addEventListener("loadedmetadata", pushDetectedMedia, { passive: true });
}

setTimeout(pushDetectedMedia, 800);
