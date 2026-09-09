// Use Bilibili's documented external player without downloading a local copy.
export function sourceVideoEmbed(pageUrl, seconds = 0) {
  try {
    const source = new URL(pageUrl);
    if (source.protocol !== "https:" || !/^(?:www\.|m\.)?bilibili\.com$/.test(source.hostname)) return "";
    const id = source.pathname.match(/^\/video\/(BV[0-9A-Za-z]+|av[0-9]+)\/?$/)?.[1];
    const part = Number(source.searchParams.get("p") || 1);
    if (!id || !Number.isSafeInteger(part) || part < 1 || !Number.isFinite(seconds) || seconds < 0) return "";
    const player = new URL("https://player.bilibili.com/player.html");
    player.searchParams.set(id.startsWith("av") ? "aid" : "bvid", id.startsWith("av") ? id.slice(2) : id);
    player.searchParams.set("p", String(part));
    player.searchParams.set("autoplay", "0");
    player.searchParams.set("danmaku", "0");
    player.searchParams.set("t", String(Math.floor(seconds)));
    return player.href;
  } catch { return ""; }
}
