// Pure platform accessibility evidence presentation; no browser or network effects.
(function installModule(global) {
  "use strict";
  const { escapeHtml, hostFromUrl, requestBodySummary, mseAppendEvidence } = global.LearnNoteTaskFormat;

function taskChaoxingProfile(task) {
  const profile = task?.recovery?.chaoxing_profile || task?.site_profiles?.chaoxing || task?.chaoxing_profile || {};
  return profile && typeof profile === "object" ? profile : {};
}

function profileYesNo(value) {
  return value ? "是" : "否";
}

function profileChip(label, value) {
  return `<span class="${value ? "pass" : "warn"}"><b>${escapeHtml(label)}</b>${escapeHtml(profileYesNo(value))}</span>`;
}

function platformSignalSiteName(task, profile = taskChaoxingProfile(task)) {
  if (profile?.detected) return "学习通/超星";
  const selected = task?.selected_resource || {};
  return hostFromUrl(task?.page_url || selected.page_url || selected.frame_url || selected.url) || "当前网站";
}

function compactEvidenceHaystack(task, profile = {}) {
  const selected = task?.selected_resource || {};
  const direct = task?.direct_extraction || {};
  const candidate = direct.selected_candidate || {};
  return [
    task?.page_url,
    selected.url,
    selected.resolved_url,
    selected.frame_url,
    selected.label,
    candidate.url,
    candidate.resolved_url,
    profile.sample_url,
    requestBodySummary(selected)
  ].filter(Boolean).join(" ");
}

function platformHeaderNames(task, profile = taskChaoxingProfile(task)) {
  const selected = task?.selected_resource || {};
  const safe = Array.isArray(profile.safe_request_header_names) ? profile.safe_request_header_names : [];
  if (safe.length) return safe;
  const headers = selected.request_headers && typeof selected.request_headers === "object"
    ? Object.keys(selected.request_headers)
    : [];
  const explicit = Array.isArray(selected.request_header_names) ? selected.request_header_names : [];
  return [...new Set([...headers, ...explicit].filter(name => !/cookie|authorization/i.test(String(name || ""))))].sort();
}

function looksLikePlayableApi(resource) {
  const text = [
    resource?.url,
    resource?.resolved_url,
    resource?.frame_url,
    resource?.label,
    resource?.request_type,
    requestBodySummary(resource)
  ].filter(Boolean).join(" ");
  return /ananas|play_?url|playURL|objectid|dtoken|httpmd|\/play(?:[/?#]|$)|playback|player|source/i.test(text);
}

function directMediaKind(kind) {
  return ["hls", "dash", "video", "audio"].includes(String(kind || "").toLowerCase());
}

function platformSignalProfile(task) {
  const profile = taskChaoxingProfile(task);
  const direct = task?.direct_extraction || {};
  const selected = task?.selected_resource || {};
  const selectedDirect = direct.selected_candidate || {};
  const browser = direct.browser_context || {};
  const preflight = profile.page_preflight || {};
  const headerNames = platformHeaderNames(task, profile);
  const requestBody = requestBodySummary(selected);
  const profileKinds = Array.isArray(profile.candidate_kinds) ? profile.candidate_kinds : [];
  const hasReplayBody = Boolean(profile.has_replay_body || selectedDirect.has_replay_body || requestBody);
  const hasFrameContext = Boolean(profile.has_iframe_context || selected.frame_url || selected.frame_id !== null && selected.frame_id !== undefined || browser.active_frame_id !== null && browser.active_frame_id !== undefined);
  const cookieCount = Number(profile.cookie_count ?? browser.cookie_count ?? 0);
  const cookieDomainCount = Number(profile.cookie_domain_count ?? browser.cookie_domain_count ?? 0);
  const hasPlayableApi = Boolean(profile.has_ananas_candidate || profile.has_playurl || profile.has_objectid || profile.has_dtoken || profile.has_httpmd || looksLikePlayableApi(selected));
  const hasDirectMedia = Boolean([selected.kind, selectedDirect.kind, ...profileKinds].some(directMediaKind) || selected.resolved_url || direct.media_landed);
  const hasPreflight = Boolean(preflight.present || task?.page_preflight_report_path);
  const downloadable = Number(preflight.downloadable_count || 0);
  const pageScan = Boolean(preflight.page_scan_attempted || preflight.page_scan_discovered_count);
  const issue = profile.likely_issue || direct.boundary || task?.error_code || "evidence_pending";
  return {
    detected: Boolean(profile.detected || task?.source_type === "current_page" || hasPlayableApi || hasDirectMedia || hasFrameContext || cookieCount || hasPreflight),
    site: platformSignalSiteName(task, profile),
    issue,
    headerNames,
    candidateKinds: profileKinds.length ? profileKinds : [selected.kind || selectedDirect.kind].filter(Boolean),
    cookieCount,
    cookieDomainCount,
    partitionedCookieCount: Number(profile.partitioned_cookie_count ?? browser.partitioned_cookie_count ?? 0),
    partitionKeyCount: Number(profile.partition_key_count ?? browser.partition_key_count ?? 0),
    preflight,
    hasPlayableApi,
    hasDirectMedia,
    hasReplayBody,
    hasReferer: Boolean(profile.has_referer || headerNames.some(name => /^referer$/i.test(name))),
    hasOrigin: Boolean(profile.has_origin || headerNames.some(name => /^origin$/i.test(name))),
    hasXRequestedWith: Boolean(profile.has_x_requested_with || headerNames.some(name => /^x-requested-with$/i.test(name))),
    hasFrameContext,
    hasBlobOrMse: Boolean(selected.blob_url || selected.kind === "blob" || mseAppendEvidence(selected) || browser.active_source_type === "blob"),
    hasPreflight,
    preflightReady: Boolean(preflight.ready || downloadable > 0),
    pageScan,
    downloadable,
    requestBody
  };
}

function chaoxingModeChecklist(task, signal, profile = taskChaoxingProfile(task)) {
  if (!profile?.detected) return "";
  const haystack = compactEvidenceHaystack(task, profile);
  const items = [
    ["ananas", Boolean(profile.has_ananas_candidate || /ananas/i.test(haystack))],
    ["playurl", Boolean(profile.has_playurl || /play_?url|playURL/i.test(haystack))],
    ["objectid", Boolean(profile.has_objectid || /objectid/i.test(haystack))],
    ["dtoken", Boolean(profile.has_dtoken || /dtoken/i.test(haystack))],
    ["iframe", Boolean(signal.hasFrameContext)],
    ["cookie", Boolean(signal.cookieCount || signal.cookieDomainCount)]
  ];
  const itemMap = Object.fromEntries(items);
  const steps = [
    {
      label: "播放器入口",
      ok: itemMap.ananas || itemMap.playurl || itemMap.objectid || signal.hasPlayableApi,
      detail: itemMap.ananas || itemMap.playurl ? "已看到 ananas/playurl 播放接口" : "先在原课程页真实播放几秒"
    },
    {
      label: "登录上下文",
      ok: itemMap.cookie && (signal.hasReferer || signal.hasFrameContext),
      detail: itemMap.cookie ? "Cookie 已同步，等待 Referer/iframe 对齐" : "需要当前登录态 Cookie"
    },
    {
      label: "接口回放",
      ok: signal.hasReplayBody || signal.hasDirectMedia,
      detail: signal.hasReplayBody ? "POST/body 可交给后端回放" : "等待 objectid/dtoken/body 或直接媒体 URL"
    },
    {
      label: "媒体落地",
      ok: signal.hasDirectMedia && (signal.preflightReady || !signal.hasPreflight),
      warn: signal.hasDirectMedia && signal.hasPreflight && !signal.preflightReady,
      detail: signal.preflightReady ? "预检已有可下载候选" : signal.hasDirectMedia ? "有媒体候选但预检未通过" : "还没有 mp4/HLS/DASH 可下载资源"
    }
  ];
  const missing = steps
    .filter(step => !step.ok)
    .map(step => step.label)
    .join("、");
  const next = missing
    ? `缺口：${missing}。继续播放几秒后重新检测；若媒体始终是 DRM/不可还原 blob，就走本地视频入口。`
    : "证据链基本完整：可以先预检，预检可下载后再开始总结或只下载到本地。";
  return `<div class="chaoxing-mode-checklist" aria-label="学习通模式证据">
    <strong>学习通模式</strong>
    <span>差哪一步一眼看清：播放接口、参数、frame 和登录态都只做可访问性诊断。</span>
    <p>${items.map(([label, ok]) => `<em class="${ok ? "pass" : "warn"}">${escapeHtml(label)} ${ok ? "已抓到" : "缺失"}</em>`).join("")}</p>
    <ol class="chaoxing-mode-flow">
      ${steps.map(step => `<li class="${step.ok ? "pass" : step.warn ? "warn" : "miss"}">
        <b>${escapeHtml(step.label)}</b>
        <small>${escapeHtml(step.detail)}</small>
      </li>`).join("")}
    </ol>
    <small class="chaoxing-mode-next">${escapeHtml(next)}</small>
  </div>`;
}

function platformSignalHtml(task) {
  const profile = taskChaoxingProfile(task);
  const signal = platformSignalProfile(task);
  if (!signal.detected) return "";
  const safeHeaders = signal.headerNames.join(", ") || "-";
  const candidateKinds = signal.candidateKinds.join(", ") || "-";
  const preflightText = signal.hasPreflight
    ? `${Number(signal.preflight.candidate_count || 0)} 候选 / ${Number(signal.preflight.probed_count || 0)} 探测 / ${Number(signal.preflight.downloadable_count || 0)} 可下载${signal.pageScan ? " / 已扫页面" : ""}`
    : "未随任务落盘";
  return `<section class="chaoxing-profile" data-platform-signal="true" aria-label="平台直取线索">
    <div class="chaoxing-profile-head">
      <span>平台线索 · ${escapeHtml(signal.site)}</span>
      <strong>${escapeHtml(signal.issue)}</strong>
    </div>
    <div class="chaoxing-profile-grid">
      ${profileChip("播放 API", signal.hasPlayableApi)}
      ${profileChip("真实媒体", signal.hasDirectMedia)}
      ${profileChip("POST/body", signal.hasReplayBody)}
      ${profileChip("Referer", signal.hasReferer)}
      ${profileChip("Origin", signal.hasOrigin)}
      ${profileChip("XHR", signal.hasXRequestedWith)}
      ${profileChip("iframe", signal.hasFrameContext)}
      ${profileChip("blob/MSE", signal.hasBlobOrMse)}
    </div>
    ${chaoxingModeChecklist(task, signal, profile)}
    <dl>
      <dt>Cookie</dt><dd>${signal.cookieDomainCount} 域 / ${signal.cookieCount} 条；分区 ${signal.partitionedCookieCount} / ${signal.partitionKeyCount} key</dd>
      <dt>预检</dt><dd>${preflightText}</dd>
      <dt>请求头</dt><dd>${escapeHtml(safeHeaders)}</dd>
      <dt>候选类型</dt><dd>${escapeHtml(candidateKinds)}</dd>
    </dl>
    <p>通用策略：优先复用当前播放暴露的媒体 URL、播放 API、iframe、Referer/Origin、一次性 Cookie 和可回放 POST body；不录制、不刷课、不伪造进度、不自动答题。</p>
  </section>`;
}

function chaoxingProfileHtml(task) {
  return platformSignalHtml(task);
}

  global.LearnNotePlatformSignals = Object.freeze({
    taskChaoxingProfile, profileYesNo, profileChip, platformSignalSiteName, compactEvidenceHaystack, platformHeaderNames, looksLikePlayableApi, directMediaKind, platformSignalProfile, chaoxingModeChecklist, platformSignalHtml, chaoxingProfileHtml
  });
})(globalThis);
