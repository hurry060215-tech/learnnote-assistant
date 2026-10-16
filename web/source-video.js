import { requestedRangeDuration, absoluteRangeTime } from "/web/range-source.js?v=decimal-range-20261016";

// Use Bilibili's documented external player without downloading a local copy.
export function sourceVideoEmbed(pageUrl, seconds = 0, rangeStart = 0) {
  try {
    const source = new URL(pageUrl);
    if (source.protocol !== "https:" || !/^(?:www\.|m\.)?bilibili\.com$/.test(source.hostname)) return "";
    const id = source.pathname.match(/^\/video\/(BV[0-9A-Za-z]+|av[0-9]+)\/?$/)?.[1];
    const part = Number(source.searchParams.get("p") || 1);
    if (!id || !Number.isSafeInteger(part) || part < 1 || !Number.isFinite(seconds) || seconds < 0 || !Number.isFinite(rangeStart) || rangeStart < 0) return "";
    const player = new URL("https://player.bilibili.com/player.html");
    player.searchParams.set(id.startsWith("av") ? "aid" : "bvid", id.startsWith("av") ? id.slice(2) : id);
    player.searchParams.set("p", String(part));
    player.searchParams.set("autoplay", "0");
    player.searchParams.set("danmaku", "0");
    player.searchParams.set("t", String(Math.floor(absoluteRangeTime(rangeStart, seconds))));
    return player.href;
  } catch { return ""; }
}

// These links are constructed locally. Unknown or signed URLs are never rewritten.
// Bilibili documents t/p at https://player.bilibili.com/; its watch-page URL is
// retained separately rather than assuming the external-player syntax applies.
export function sourcePageNavigation(source, seconds) {
  const value = source?.kind === "task" && source.page_url;
  if (typeof value !== "string" || /[\u0000-\u0020\u007f]/.test(value)) return null;
  let page;
  try { page = new URL(value); } catch { return null; }
  if (!["http:", "https:"].includes(page.protocol) || page.username || page.password) return null;
  const result = { originalHref: value, timedHref: "", seconds: null, provider: "", reason: "" };
  if (seconds === undefined) return result;
  const range = source.learning_range || {}, hasRange = Object.keys(range).length > 0;
  const offset = hasRange ? (range.original_start ?? range.start) : 0;
  const absoluteSeconds = absoluteRangeTime(offset, seconds);
  if (![seconds, offset].every(number => typeof number === "number" && Number.isFinite(number) && number >= 0) ||
      !Number.isSafeInteger(Math.floor(absoluteSeconds)) ||
      (hasRange && (![range.start, range.end].every(number => typeof number === "number" && Number.isFinite(number) && number >= 0) ||
        range.end <= range.start || seconds > requestedRangeDuration(range) ||
        (range.original_end !== undefined && (!Number.isFinite(range.original_end) || seconds > requestedRangeDuration({start: offset, end: range.original_end})))))) {
    result.reason = "invalid_time";
    return result;
  }
  result.seconds = absoluteSeconds;
  const signed = [...page.searchParams.keys()].some(key => /^(?:token|access_token|sign|signature|sig|expires?|deadline|auth|auth_key|api_key|key|key-pair-id|policy|wsSecret|wsTime|x-amz-.+|x-goog-.+)$/i.test(key));
  if (signed || page.port) { result.reason = "manual"; return result; }
  const host = page.hostname.toLowerCase(), position = Math.floor(result.seconds);
  if (/^(?:www\.|m\.)?bilibili\.com$/.test(host)) {
    // A cid can override p in the provider player. Keep it manual rather than
    // dropping explicit content identity or guessing its relation to this page.
    if (page.searchParams.has("cid") || page.searchParams.getAll("p").length > 1 || (page.searchParams.has("p") && !/^[1-9]\d*$/.test(page.searchParams.get("p")))) {
      result.reason = "manual"; return result;
    }
    result.timedHref = sourceVideoEmbed(value, position);
    if (result.timedHref) result.provider = "Bilibili";
  } else if (["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"].includes(host)) {
    const id = host === "youtu.be" ? page.pathname.match(/^\/([A-Za-z0-9_-]{11})\/?$/)?.[1]
      : page.pathname === "/watch" && page.searchParams.getAll("v").length === 1 ? page.searchParams.get("v") : "";
    if (/^[A-Za-z0-9_-]{11}$/.test(id || "")) {
      page.searchParams.delete("start"); page.searchParams.delete("end");
      page.searchParams.set("t", `${position}s`);
      page.hash = "";
      result.timedHref = page.href; result.provider = "YouTube";
    }
  }
  if (!result.timedHref) result.reason = "manual";
  return result;
}
