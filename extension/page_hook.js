(function () {
  if (window.__learnNotePageHookInstalled) return;
  window.__learnNotePageHookInstalled = true;

  const MEDIA_URL_RE = /(?:https?:)?\/\/[^\s"'<>\\]+\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:\?[^\s"'<>\\]*)?|(?:\/[^\s"'<>\\]+)\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:\?[^\s"'<>\\]*)?|(?:[A-Za-z0-9._~!$&()*+,;=:@%-]+\/)*[A-Za-z0-9._~!$&()*+,;=:@%-]+\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:\?[^\s"'<>\\]*)?/gi;
  const MEDIA_HINT_RE = /\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:[?#]|["'\s<>]|$)/i;
  const TEXT_TYPE_RE = /json|text|javascript|mpegurl|dash\+xml|xml|x-mpegurl/i;
  const MAX_TEXT_BYTES = 2 * 1024 * 1024;
  const bufferedResources = [];

  function normalizeUrl(raw) {
    if (!raw) return "";
    const cleaned = String(raw)
      .replace(/\\\//g, "/")
      .replace(/\\u0026/g, "&")
      .replace(/&amp;/g, "&")
      .trim();
    try {
      return new URL(cleaned, location.href).href;
    } catch {
      return "";
    }
  }

  function mediaKind(url, mime = "") {
    const lower = String(url || "").toLowerCase();
    const type = String(mime || "").toLowerCase();
    if (type.includes("mpegurl") || lower.includes(".m3u8")) return "hls";
    if (type.includes("dash+xml") || lower.includes(".mpd")) return "dash";
    if (type.includes("text/vtt") || type.includes("subrip") || /\.(vtt|srt|ass|ssa)(\?|#|$)/i.test(lower)) return "subtitle";
    if (type.includes("video/") || /\.(mp4|m4v|webm|mov|mkv)(\?|#|$)/i.test(lower)) return "video";
    return "unknown";
  }

  function post(resources) {
    if (!resources?.length) return;
    window.postMessage({ source: "learnnote-page-hook", resources }, "*");
  }

  function emit(resources) {
    const deduped = [];
    const seen = new Set();
    for (const item of resources || []) {
      const url = normalizeUrl(item.url);
      if (!url || seen.has(url)) continue;
      const kind = mediaKind(url, item.mime || "");
      if (kind === "unknown") continue;
      seen.add(url);
      deduped.push({
        url,
        source: item.source || "pageHook",
        kind,
        mime: item.mime || "",
        label: item.label || "page hook",
        score: item.score || (kind === "hls" || kind === "dash" ? 96 : kind === "video" ? 88 : 62)
      });
    }
    if (!deduped.length) return;
    for (const item of deduped) {
      if (!bufferedResources.some(resource => resource.url === item.url)) bufferedResources.unshift(item);
    }
    bufferedResources.splice(100);
    post(deduped);
  }

  function extractUrlsFromText(text, source, label, mime = "") {
    if (!text || !MEDIA_HINT_RE.test(text)) return;
    const resources = [];
    for (const match of text.matchAll(MEDIA_URL_RE)) {
      resources.push({ url: match[0], source, label, mime });
      if (resources.length >= 40) break;
    }
    emit(resources);
  }

  function shouldInspectResponse(response) {
    const type = response.headers?.get?.("content-type") || "";
    const length = Number(response.headers?.get?.("content-length") || 0);
    if (length && length > MAX_TEXT_BYTES) return false;
    return TEXT_TYPE_RE.test(type);
  }

  function requestUrl(input) {
    try {
      if (typeof input === "string") return input;
      if (input && typeof input.url === "string") return input.url;
    } catch {
      return "";
    }
    return "";
  }

  if (typeof window.fetch === "function") {
    const originalFetch = window.fetch;
    window.fetch = async function (...args) {
      const response = await originalFetch.apply(this, args);
      const url = response.url || requestUrl(args[0]);
      emit([{ url, source: "pageHookRequest", label: "fetch", mime: response.headers?.get?.("content-type") || "" }]);
      if (shouldInspectResponse(response)) {
        response.clone().text()
          .then(text => extractUrlsFromText(text.slice(0, MAX_TEXT_BYTES), "pageHookBody", "fetch body", response.headers?.get?.("content-type") || ""))
          .catch(() => {});
      }
      return response;
    };
  }

  if (typeof window.XMLHttpRequest === "function") {
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      this.__learnNoteUrl = url;
      return originalOpen.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function (...args) {
      this.addEventListener("loadend", () => {
        const url = this.responseURL || this.__learnNoteUrl || "";
        const mime = this.getResponseHeader?.("content-type") || "";
        emit([{ url, source: "pageHookRequest", label: "xhr", mime }]);
        if (!TEXT_TYPE_RE.test(mime)) return;
        if (this.responseType && this.responseType !== "text") return;
        let text = "";
        try {
          text = typeof this.response === "string" ? this.response : this.responseText;
        } catch {
          text = "";
        }
        if (typeof text !== "string") return;
        extractUrlsFromText(text.slice(0, MAX_TEXT_BYTES), "pageHookBody", "xhr body", mime);
      });
      return originalSend.apply(this, args);
    };
  }

  window.addEventListener("message", event => {
    if (event.source !== window || event.data?.source !== "learnnote-content-ready") return;
    post(bufferedResources);
  });
})();
