// Cookie lookup planning and partition selection; browser access must be injected by the caller.
(function (root) {
function cookieEligibleUrl(value) {
  const url = String(value || "").trim();
  if (/^https?:\/\//i.test(url)) return url;
  const blob = /^blob:(https?:\/\/[^/]+)/i.exec(url);
  return blob ? blob[1] : "";
}

function cookieDomainCandidates(value) {
  const url = cookieEligibleUrl(value);
  if (!url) return [];
  try {
    const host = new URL(url).hostname;
    if (!host || /^\d+\.\d+\.\d+\.\d+$/.test(host) || host === "localhost") return host ? [host] : [];
    const parts = host.split(".").filter(Boolean);
    const domains = [];
    for (let index = 0; index <= Math.max(0, parts.length - 2); index += 1) {
      const domain = parts.slice(index).join(".");
      if (domain && !domains.includes(domain)) domains.push(domain);
    }
    return domains;
  } catch {
    return [];
  }
}

function normalizedCookiePartitionKey(key = null) {
  if (!key || typeof key !== "object") return null;
  const normalized = {};
  if (typeof key.topLevelSite === "string" && key.topLevelSite) normalized.topLevelSite = key.topLevelSite;
  if (typeof key.hasCrossSiteAncestor === "boolean") normalized.hasCrossSiteAncestor = key.hasCrossSiteAncestor;
  return Object.keys(normalized).length ? normalized : null;
}

function cookiePartitionKeyId(key = null) {
  const normalized = normalizedCookiePartitionKey(key);
  return normalized ? JSON.stringify(normalized) : "";
}

function cookiePartitionPreference(partitionKeys = []) {
  const ranks = new Map();
  for (const partitionKey of partitionKeys || []) {
    const id = cookiePartitionKeyId(partitionKey);
    if (id && !ranks.has(id)) ranks.set(id, ranks.size);
  }
  return ranks;
}

function cookieLookupDetailsForUrls(urls, partitionKeys = []) {
  const details = [];
  const seen = new Set();
  const add = detail => {
    const key = JSON.stringify(detail);
    if (seen.has(key)) return;
    seen.add(key);
    details.push(detail);
  };
  const addWithPartitions = detail => {
    for (const partitionKey of partitionKeys || []) {
      const normalized = normalizedCookiePartitionKey(partitionKey);
      if (normalized) add({ ...detail, partitionKey: normalized });
    }
    add(detail);
  };

  for (const raw of urls || []) {
    const url = cookieEligibleUrl(raw);
    if (!/^https?:\/\//i.test(url)) continue;
    addWithPartitions({ url });
    for (const domain of cookieDomainCandidates(url)) {
      addWithPartitions({ domain });
    }
  }
  return details;
}

function cookieContextSummary(cookies = [], urls = [], partitionKeys = []) {
  const domains = new Map();
  let partitioned = 0;
  for (const cookie of cookies || []) {
    const domain = String(cookie.domain || "").replace(/^\./, "") || "(host)";
    domains.set(domain, (domains.get(domain) || 0) + 1);
    if (cookie.partitionKey) partitioned += 1;
  }
  const domainSummary = [...domains.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, 8)
    .map(([domain, count]) => ({ domain, count }));
  return {
    count: cookies.length,
    domain_count: domains.size,
    partitioned_count: partitioned,
    partition_key_count: partitionKeys.length,
    target_count: urls.length,
    domains: domainSummary
  };
}

function cookieUrlsForContext(page = {}, tab = {}, resources = []) {
  const urls = [];
  const add = value => {
    const url = cookieEligibleUrl(value);
    if (!url) return;
    if (!urls.includes(url)) urls.push(url);
  };

  add(page.page_url);
  add(tab.url);
  add(page.active_video?.src);
  add(page.active_video?.frame_url);
  for (const frame of page.frames || []) {
    add(frame.page_url);
  }

  for (const resource of resources || []) {
    add(resource.url);
    add(resource.resolved_url);
    add(resource.page_url);
    add(resource.frame_url);
    add(resource.initiator);
    add(resource.blob_url);
    const headers = resource.request_headers || {};
    for (const [name, value] of Object.entries(headers)) {
      if (/^(referer|origin)$/i.test(name)) add(value);
    }
    const responseHeaders = resource.headers || {};
    for (const [name, value] of Object.entries(responseHeaders)) {
      if (/^(location|content-location)$/i.test(name)) add(value);
    }
  }
  return urls;
}

function createCookieContext({ getCookies }) {
  async function cookiePartitionKeysForContext(page = {}, tab = {}, resources = []) {
    if (!getCookies()?.getPartitionKey || !Number.isFinite(tab.id)) return [];
    const frameIds = [];
    const addFrameId = value => {
      const frameId = Number(value);
      if (!Number.isFinite(frameId) || frameId < 0 || frameIds.includes(frameId)) return;
      frameIds.push(frameId);
    };
    addFrameId(0);
    addFrameId(page.active_video?.frame_id);
    for (const frame of page.frames || []) addFrameId(frame.frame_id);
    for (const resource of resources || []) addFrameId(resource.frame_id);

    const keys = [];
    const seen = new Set();
    for (const frameId of frameIds) {
      try {
        const key = normalizedCookiePartitionKey(await getCookies().getPartitionKey({ tabId: tab.id, frameId }));
        if (!key) continue;
        const id = JSON.stringify(key);
        if (seen.has(id)) continue;
        seen.add(id);
        keys.push(key);
      } catch {
        // Older browsers or inaccessible frames can continue with unpartitioned cookies.
      }
    }
    return keys;
  }

  async function cookiesForUrls(urls, partitionKeys = []) {
    const exactCookies = new Map();
    const partitionRanks = cookiePartitionPreference(partitionKeys);
    let ordinal = 0;
    for (const details of cookieLookupDetailsForUrls(urls, partitionKeys)) {
      try {
        const cookies = await getCookies().getAll(details);
        for (const cookie of cookies) {
          const partitionKey = normalizedCookiePartitionKey(cookie.partitionKey) || normalizedCookiePartitionKey(details.partitionKey);
          const normalizedCookie = partitionKey ? { ...cookie, partitionKey } : { ...cookie };
          const partitionId = cookiePartitionKeyId(partitionKey);
          const key = `${normalizedCookie.domain}|${normalizedCookie.path}|${normalizedCookie.name}|${partitionId}`;
          if (!exactCookies.has(key)) {
            exactCookies.set(key, {
              cookie: normalizedCookie,
              partitionId,
              ordinal: ordinal++
            });
          }
        }
      } catch {
        // Ignore browser-internal, malformed, or unsupported cookie lookups.
      }
    }

    const grouped = new Map();
    const hasPreferredPartitions = partitionRanks.size > 0;
    for (const record of exactCookies.values()) {
      const cookie = record.cookie;
      const identity = `${cookie.domain}|${cookie.path}|${cookie.name}`;
      const partitionRank = partitionRanks.has(record.partitionId) ? partitionRanks.get(record.partitionId) : null;
      const partitionScore = partitionRank !== null
        ? 10000 - partitionRank
        : (record.partitionId ? 5000 : (hasPreferredPartitions ? 0 : 1000));
      const scored = { ...record, score: partitionScore };
      const previous = grouped.get(identity);
      if (!previous || scored.score > previous.score || (scored.score === previous.score && scored.ordinal < previous.ordinal)) {
        grouped.set(identity, scored);
      }
    }

    return [...grouped.values()]
      .sort((left, right) => left.ordinal - right.ordinal)
      .map(record => record.cookie);
  }

  return Object.freeze({ cookiePartitionKeysForContext, cookiesForUrls });
}

root.LearnNoteCookieContext = Object.freeze({
  cookieLookupDetailsForUrls,
  cookieContextSummary,
  cookieUrlsForContext,
  createCookieContext,
});
})(globalThis);
