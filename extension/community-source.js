/* Exact public video identity for the explicit community snapshot. No I/O. */
(function (root) {
  "use strict";
  function canonicalPage(value) {
    try {
      const url = new URL(value);
      if (url.protocol !== "https:" || url.username || url.password || url.port || !["www.bilibili.com", "bilibili.com"].includes(url.hostname)) return "";
      const match = /^\/video\/(BV[A-Za-z0-9]{10}|av[0-9]{1,20})\/?$/.exec(url.pathname);
      const parts = url.searchParams.getAll("p");
      if (!match || parts.length > 1 || (parts.length && !/^[1-9][0-9]{0,5}$/.test(parts[0]))) return "";
      return `https://www.bilibili.com/video/${match[1]}?p=${parts[0] || "1"}`;
    } catch { return ""; }
  }
  function localOrigin(value) {
    try {
      const url = new URL(value);
      if (url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname) && !url.username && !url.password && !url.search && !url.hash && url.pathname === "/") return url.origin;
    } catch {}
    return "";
  }
  root.LearnNoteCommunitySource = Object.freeze({ canonicalPage, localOrigin });
})(globalThis);
