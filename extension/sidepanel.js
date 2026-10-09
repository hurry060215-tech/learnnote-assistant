const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";
const PROTOCOL_VERSION = 1;
const HEALTH_TIMEOUT_MS = 2200;
const REQUEST_TIMEOUT_MS = 20000;
const PASSIVE_REFRESH_DELAY_MS = 450;
const PREFLIGHT_TTL_MS = 30000;
const CLIENT_TAB_ACTIVATION_SUPPRESS_MS = 3000;
const CLIENT_START_TIMEOUT_MS = 45000;
const LOCAL_BACKEND_RE = /^http:\/\/(?:127\.0\.0\.1|localhost)(?::\d{1,5})?\/?$/i;
const MEDIA_KIND_RE = /^(?:video|media|mp4|hls|dash|manifest|playlist)$/i;
const AUDIO_KIND_RE = /audio/i;
const SUBTITLE_KIND_RE = /subtitle|caption|vtt|srt/i;
const t = (key, values) => globalThis.LearnNoteI18n.message(key, values);
const productMessage = value => globalThis.LearnNoteI18n.productMessage(value);

const HAS_EXTENSION_API = typeof chrome !== "undefined" && Boolean(chrome.runtime?.sendMessage && chrome.storage?.local);

const els = {
  connectionCard: document.querySelector("#connectionCard"),
  connectionTitle: document.querySelector("#connectionTitle"),
  connectionDetail: document.querySelector("#connectionDetail"),
  openClientButton: document.querySelector("#openClientButton"),
  clientInstallHelp: document.querySelector("#clientInstallHelp"),
  openClientBrand: document.querySelector("#openClientBrand"),
  refreshButton: document.querySelector("#refreshButton"),
  platformLabel: document.querySelector("#platformLabel"),
  playingBadge: document.querySelector("#playingBadge"),
  videoTitle: document.querySelector("#videoTitle"),
  videoMeta: document.querySelector("#videoMeta"),
  integrityGrid: document.querySelector("#integrityGrid"),
  candidateCount: document.querySelector("#candidateCount"),
  durationValue: document.querySelector("#durationValue"),
  estimateValue: document.querySelector("#estimateValue"),
  preflightMessage: document.querySelector("#preflightMessage"),
  modeDescription: document.querySelector("#modeDescription"),
  extensionOptions: document.querySelector("#extensionOptions"),
  sendButton: document.querySelector("#sendButton"),
  sendButtonLabel: document.querySelector("#sendButtonLabel"),
  handoffProgress: document.querySelector("#handoffProgress"),
  handoffStatus: document.querySelector("#handoffStatus"),
  handoffPercent: document.querySelector("#handoffPercent"),
  openTaskButton: document.querySelector("#openTaskButton"),
  quickResultCard: document.querySelector("#quickResultCard"),
  quickResultStatus: document.querySelector("#quickResultStatus"),
  quickDeepButton: document.querySelector("#quickDeepButton"),
  quickSummaryPanel: document.querySelector("#quickSummaryPanel"),
  quickTranscriptPanel: document.querySelector("#quickTranscriptPanel"),
  quickAskPanel: document.querySelector("#quickAskPanel"),
  quickAskConversation: document.querySelector("#quickAskConversation"),
  quickAskForm: document.querySelector("#quickAskForm"),
  quickAskQuestion: document.querySelector("#quickAskQuestion"),
  permissionDetails: document.querySelector("#permissionDetails"),
  permissionList: document.querySelector("#permissionList"),
  permissionStatus: document.querySelector("#permissionStatus")
};

let backendUrl = DEFAULT_BACKEND_URL;
let clientConnected = false;
let modelReadiness = { configured: null, model: "", supportsVision: null };
let currentContext = null;
let displayedIdentity = null;
let preflightReport = null;
let preflightIdentity = null;
let currentTaskId = "";
let sending = false;
let refreshTimer = 0;
let contextGeneration = 0;
let collectRequest = null;
let sitePermissionEpoch = 0;
let preflightRequest = null;
let preflightAt = 0;
let preflightFingerprint = "";
let activeHandoff = null;
let suppressTabActivationUntil = 0;
let currentTaskMode = "";
let quickTranscript = [];
let selectedProcessingMode = "study";
let currentTaskContentMode = "";
let connectionRequest = null;
let clientOpenRequest = null;
let quickQuestionPending = false;
let activationGeneration = 0;

function baseProcessingOptions(mode = selectedProcessingMode) {
  if (mode === "deep") return { content_mode: "visual", visual_understanding: true, frame_interval: 20, grid_columns: 3, grid_rows: 3, note_style: "lecture", note_template: "visual-handout", summary_depth: "deep" };
  if (mode === "study") return { content_mode: "text", visual_understanding: false, note_style: "classroom-review", note_template: "standard", summary_depth: "standard" };
  return { content_mode: "subtitles", visual_understanding: false, note_style: "quick-summary", note_template: "timeline", summary_depth: "brief" };
}

let quickNoteText = "";
function processingOptions(mode = selectedProcessingMode) {
  const options=baseProcessingOptions(mode);
  const style=document.querySelector?.("#extensionStyle")?.value;
  const template=document.querySelector?.("#extensionTemplate")?.value;
  const prompt=document.querySelector?.("#extensionPrompt")?.value;
  if(style)options.note_style=style;
  if(template)options.note_template=template;
  if(prompt)options.note_profile_prompt=String(prompt).slice(0,4000);
  return options;
}
function downloadResult(text,name,type) {
  const blob=new Blob([text],{type}),url=URL.createObjectURL(blob),a=document.createElement("a");
  a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function subtitleSrt(cues) {
  const stamp=value=>{const ms=Math.max(0,Math.round(Number(value||0)*1000));return `${String(Math.floor(ms/3600000)).padStart(2,"0")}:${String(Math.floor(ms/60000)%60).padStart(2,"0")}:${String(Math.floor(ms/1000)%60).padStart(2,"0")},${String(ms%1000).padStart(3,"0")}`;};
  return cues.map((c,i)=>`${i+1}\n${stamp(c.start)} --> ${stamp(c.end)}\n${c.text}\n`).join("\n");
}
function setProcessingMode(mode = "study", persist = true) {
  if (sending) return;
  const nextMode = ["quick", "study", "deep"].includes(mode) ? mode : "study";
  if (nextMode !== selectedProcessingMode && currentTaskId) resetSourceState(true);
  selectedProcessingMode = nextMode;
  document.querySelectorAll?.("[data-processing-mode]").forEach(button => {
    const active = button.dataset.processingMode === selectedProcessingMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-checked", String(active));
    button.setAttribute("tabindex", active ? "0" : "-1");
  });
  if (persist && HAS_EXTENSION_API) chrome.storage.local.set({ processingMode: selectedProcessingMode }).catch(() => {});
  renderContext();
}

function subtitleCues(context = currentContext) {
  return (context?.page?.browser_subtitles || [])
    .map(item => ({ start: Number(item?.start || 0), end: Number(item?.end || item?.start || 0), text: String(item?.text || "").trim() }))
    .filter(item => item.text && Number.isFinite(item.start) && Number.isFinite(item.end) && item.end >= item.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);
}

function hasReliableBrowserSubtitles(context = currentContext) {
  const cues = subtitleCues(context);
  if (!cues.length) return false;
  const windows = new Map();
  for (const cue of cues) {
    const key = `${Math.round(cue.start)}:${Math.round(cue.end)}`;
    windows.set(key, (windows.get(key) || 0) + 1);
  }
  const largestCollision = Math.max(...windows.values());
  if (largestCollision >= 4 && largestCollision / cues.length >= 0.4) return false;
  const duration = Number(context?.page?.active_video?.duration || 0);
  const span = Math.max(0, Math.max(...cues.map(cue => cue.end)) - cues[0].start);
  if (duration > 0) return span / duration >= 0.55;
  return cues.length >= 8 && span >= 45;
}

function escapeQuickHtml(value = "") {
  return String(value).replace(/[&<>\"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[char]);
}

function quickInline(text) {
  return escapeQuickHtml(text).replace(/`?(\b\d{1,3}:\d{2}(?::\d{2})?\b)`?/g,(match,time)=>{
    const parts=time.split(":").map(Number);if(parts.at(-1)>59||(parts.length===3&&parts[1]>59))return match;
    const seconds=parts.reduce((total,part)=>total*60+part,0);
    return `<button type="button" class="summary-time" data-seek-time="${seconds}">${time}</button>`;
  });
}
function bindQuickSeek(container) {
  container?.querySelectorAll?.("[data-seek-time]").forEach(button=>button.addEventListener("click",async()=>{
    await seekSourceVideo(Number(button.dataset.seekTime));
  }));
}
async function seekSourceVideo(seconds) {
  const status = document.querySelector("#sourceSeekStatus");
  if (!HAS_EXTENSION_API || !displayedIdentity?.tab_id) return;
  try {
    const result = await chrome.runtime.sendMessage({type:"seek-current-video", targetTabId:displayedIdentity.tab_id,
      expectedUrl:currentContext?.tab?.url || currentContext?.page?.page_url, seconds});
    if (!result?.ok) throw new Error(productMessage(result?.error) || t("ui_return_to_the_original_video_page_and_try_again"));
    if (status) status.textContent = t("seek_position", { time: formatCueTime(seconds) });
  } catch (error) { if (status) status.textContent = productMessage(error.message) || t("ui_unable_to_seek_open_the_original_video"); }
}

function groupSubtitleParagraphs(cues) {
  const groups = [];
  let current = [], length = 0;
  for (const cue of cues) {
    const last = current.at(-1);
    if (last && (cue.start - last.end > 3 || length >= 360 || (length >= 180 && /[。！？.!?]$/.test(last.text)))) {
      groups.push(current); current = []; length = 0;
    }
    current.push(cue); length += cue.text.length;
  }
  if (current.length) groups.push(current);
  return groups;
}
let previewSignature = "";
function renderSourcePreview() {
  const card = document.querySelector("#sourcePreviewCard"), content = document.querySelector("#sourcePreviewContent");
  if (!card || !content) return;
  const cues = quickTranscript.length && currentTaskId ? quickTranscript : subtitleCues();
  card.hidden = !cues.length;
  const query = (document.querySelector("#subtitleSearch")?.value || "").trim().toLocaleLowerCase();
  const signature = JSON.stringify([displayedIdentity ? sourceContinuityKey(displayedIdentity) : "", cues, query]);
  if (previewSignature === signature) return;
  previewSignature = signature;
  const groups = groupSubtitleParagraphs(cues).filter(group => !query || group.some(cue => cue.text.toLocaleLowerCase().includes(query)));
  document.querySelector("#sourcePreviewCount").textContent = t("preview_counts", { cues: cues.length, groups: groups.length });
  content.innerHTML = groups.map((group, index) => `<details class="subtitle-paragraph" ${query || index === 0 ? "open" : ""}><summary><time>${formatCueTime(group[0].start)}</time><span>${escapeQuickHtml(group.map(c=>c.text).join(" ").slice(0,42))}</span></summary>${group.filter(cue=>!query || cue.text.toLocaleLowerCase().includes(query)).map(cue=>`<button class="quick-transcript-cue" type="button" data-seek-time="${cue.start}"><time>${formatCueTime(cue.start)}</time><span>${escapeQuickHtml(cue.text)}</span></button>`).join("")}</details>`).join("") || `<p>${escapeQuickHtml(t("ui_no_matching_subtitles"))}</p>`;
  bindQuickSeek(content);
}
function renderQuickMarkdown(markdown = "") {
  const lines = String(markdown || "").split(/\r?\n/);
  const html = [];
  let list = false;
  const closeList = () => { if (list) { html.push("</ul>"); list = false; } };
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { closeList(); continue; }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    const bullet = /^[-*]\s+(.+)$/.exec(line);
    if (heading) { closeList(); html.push(`<h${heading[1].length}>${escapeQuickHtml(heading[2])}</h${heading[1].length}>`); continue; }
    if (bullet) { if (!list) { html.push("<ul>"); list = true; } html.push(`<li>${quickInline(bullet[1])}</li>`); continue; }
    closeList();
    html.push(`<p>${quickInline(line).replace(/`([^`]+)`/g, "<code>$1</code>")}</p>`);
  }
  closeList();
  return html.join("") || `<p>${escapeQuickHtml(t("ui_waiting_for_the_result"))}</p>`;
}

function formatCueTime(seconds) {
  const total = Math.max(0, Math.round(Number(seconds || 0)));
  const minutes = Math.floor(total / 60);
  return `${String(minutes).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function showQuickResult(status = t("ui_processing_subtitles")) {
  if (!els.quickResultCard) return;
  els.quickResultCard.hidden = false;
  if (els.quickResultStatus) els.quickResultStatus.textContent = status;
  const extractedOnly = currentTaskContentMode === "subtitles";
  document.querySelectorAll?.('[data-quick-tab="summary"], [data-quick-tab="ask"], #copyQuickSummary, #saveQuickSummary').forEach(item => { item.hidden = extractedOnly; });
}

function renderQuickTranscript(cues = quickTranscript) {
  if (!els.quickTranscriptPanel) return;
  els.quickTranscriptPanel.innerHTML = cues.length
    ? cues.map(cue => `<button type="button" class="quick-transcript-cue" data-seek-time="${Number(cue.start).toFixed(3)}"><time>${formatCueTime(cue.start)}</time><span>${escapeQuickHtml(cue.text)}</span></button>`).join("")
    : `<p>${escapeQuickHtml(t("ui_subtitles_have_not_been_loaded_yet"))}</p>`;
  els.quickTranscriptPanel.querySelectorAll?.("[data-seek-time]").forEach(button => {
    button.addEventListener("click", async () => {
      if (!HAS_EXTENSION_API || !displayedIdentity?.tab_id) return;
      await seekSourceVideo(Number(button.dataset.seekTime));
    });
  });
}

function setQuickTab(tabName = "summary") {
  document.querySelectorAll?.("[data-quick-tab]").forEach(button => {
    const active = button.dataset.quickTab === tabName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll?.("[data-quick-panel]").forEach(panel => {
    panel.hidden = panel.dataset.quickPanel !== tabName;
  });
}

async function loadQuickArtifacts(task, reader) {
  const [noteResponse, transcriptResponse] = await Promise.all([
    fetch(`${reader.base}/note`, { signal: reader.signal, redirect: "error" }),
    fetch(`${reader.base}/transcript`, { signal: reader.signal, redirect: "error" })
  ]);
  const note = noteResponse.ok ? await noteResponse.text() : "";
  const transcript = transcriptResponse.ok ? await transcriptResponse.json() : {};
  if (!reader.isCurrent()) return;
  quickNoteText=note;
  quickTranscript = Array.isArray(transcript?.segments) ? transcript.segments : [];
  if (els.quickSummaryPanel) els.quickSummaryPanel.innerHTML = renderQuickMarkdown(note);
  bindQuickSeek(els.quickSummaryPanel);
  renderQuickTranscript(quickTranscript);
  renderSourcePreview();
  const extractedOnly = (task.options?.content_mode || currentTaskContentMode) === "subtitles";
  showQuickResult(extractedOnly ? t("ui_transcript_saved_no_model_used") : (task.summary_warning ? t("note_warning", { warning: productMessage(task.summary_warning) }) : t("ui_text_note_complete_no_video_downloaded")));
  if (extractedOnly) setQuickTab("transcript");
}

const progressiveReader = globalThis.LearnNoteProgressive.create({
  card: document.querySelector("#progressiveCard"), status: document.querySelector("#progressiveStatus"),
  sections: document.querySelector("#progressiveSections"), retry: document.querySelector("#progressiveRetry"), document, t,
  onProgress: task => { if (currentTaskMode === "subtitle_only") showQuickResult(productMessage(task.message) || t("ui_reading_subtitles")); },
  onStop: async (state, reader) => {
    if (currentTaskMode !== "subtitle_only" || state === "success") return;
    showQuickResult(t(state === "cancelling" ? "progress_cancelling" : state === "cancelled" ? "progress_cancelled" : "progress_failed"));
    const response = await fetch(`${reader.base}/transcript`, { signal: reader.signal, redirect: "error" });
    if (!response.ok) return;
    const transcript = await response.json();
    if (reader.isCurrent() && Array.isArray(transcript.segments)) { quickTranscript = transcript.segments; renderQuickTranscript(); renderSourcePreview(); }
  },
  onTask: async (task, reader) => {
    if (currentTaskMode !== "subtitle_only" || !task.note_path) return;
    await loadQuickArtifacts(task, reader);
    if (reader.isCurrent()) setProgress(100, currentTaskContentMode === "subtitles" ? t("ui_transcript_extracted_save_the_srt_file_or_choose_to_generate_a") : t("ui_your_text_note_is_ready_to_read_revisit_or_export"), "success");
  }
});
function startProgressiveReading() {
  progressiveReader.start({ backendUrl, taskId: currentTaskId, sourceKey: sourceContinuityKey(displayedIdentity) });
}
window.addEventListener("pagehide", () => progressiveReader.suspend());
window.addEventListener("pageshow", () => progressiveReader.resume());

function withTimeout(promise, timeoutMs, label) {
  let timer = 0;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(t("operation_timeout", { operation: label }))), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function normalizedBackendUrl(value) {
  const candidate = String(value || "").trim().replace(/\/$/, "");
  return LOCAL_BACKEND_RE.test(candidate) ? candidate : DEFAULT_BACKEND_URL;
}

function canonicalPageUrl(value = "") {
  try {
    const url = new URL(value);
    url.hash = "";
    url.hostname = url.hostname.toLowerCase();
    const keep = new Set(["v", "p", "list", "index", "courseId", "clazzid", "knowledgeId", "chapterId", "objectid"]);
    for (const key of [...url.searchParams.keys()]) {
      if (!keep.has(key)) url.searchParams.delete(key);
    }
    if ((url.protocol === "https:" && url.port === "443") || (url.protocol === "http:" && url.port === "80")) url.port = "";
    url.pathname = url.pathname.replace(/\/{2,}/g, "/");
    if (url.pathname !== "/") url.pathname = url.pathname.replace(/\/$/, "");
    url.searchParams.sort();
    return url.href;
  } catch {
    return String(value || "").split("#")[0].trim();
  }
}

function hostnameMatches(hostname = "", domain = "") {
  const host = String(hostname || "").toLowerCase().replace(/\.$/, "");
  const root = String(domain || "").toLowerCase().replace(/\.$/, "");
  return host === root || host.endsWith(`.${root}`);
}

function platformIdentity(urlValue = "", page = {}) {
  const url = String(urlValue || "");
  const bilibili = /(?:bilibili\.com\/video\/|b23\.tv\/)(BV[0-9A-Za-z]+)/i.exec(url);
  if (bilibili) return { platform: "bilibili", platformVideoId: bilibili[1], label: t("ui_bilibili") };
  try {
    const parsed = new URL(url);
    if (hostnameMatches(parsed.hostname, "youtube.com") || hostnameMatches(parsed.hostname, "youtu.be")) {
      const id = hostnameMatches(parsed.hostname, "youtu.be") ? parsed.pathname.split("/").filter(Boolean)[0] : parsed.searchParams.get("v");
      return { platform: "youtube", platformVideoId: id || "", label: "YouTube" };
    }
    if (hostnameMatches(parsed.hostname, "chaoxing.com") || /xuexitong/i.test(parsed.hostname)) {
      const active = page.active_video || {};
      const id = parsed.searchParams.get("objectid") || parsed.searchParams.get("knowledgeId") || active.objectid || page.objectid || "";
      return { platform: "chaoxing", platformVideoId: String(id), label: t("ui_xuexitong_chaoxing") };
    }
    return { platform: parsed.hostname.replace(/^www\./, "") || "web", platformVideoId: "", label: parsed.hostname.replace(/^www\./, "") || t("currentPage") };
  } catch {
    return { platform: "web", platformVideoId: "", label: t("currentPage") };
  }
}

function stableMediaUrl(value = "") {
  try {
    const url = new URL(value);
    url.hash = "";
    const volatile = /^(?:token|sign|signature|expires?|deadline|auth|auth_key|wsSecret|wsTime|timestamp|ts|t|rnd|random|callback)$/i;
    for (const key of [...url.searchParams.keys()]) {
      if (volatile.test(key)) url.searchParams.delete(key);
    }
    url.searchParams.sort();
    return url.href;
  } catch {
    return String(value || "").split("#")[0];
  }
}

function fnv1a(value = "") {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function resourceFingerprint(page = {}, resources = []) {
  const stable = [];
  const active = page.active_video || {};
  const activeSrc = active.current_src || active.currentSrc || active.src || "";
  if (activeSrc) stable.push(`active:${stableMediaUrl(activeSrc)}`);
  const ranked = [...(resources || [])]
    .filter(item => item?.url && !SUBTITLE_KIND_RE.test(String(item.kind || "")))
    .sort((left, right) => Number(right.score || 0) - Number(left.score || 0));
  for (const item of ranked) {
    const url = stableMediaUrl(item.resolved_url || item.url);
    if (!url) continue;
    const kind = String(item.kind || "media").toLowerCase();
    const key = `${kind}:${url}`;
    if (!stable.includes(key)) stable.push(key);
    if (stable.length >= 12) break;
  }
  return fnv1a(stable.sort().join("\n") || "no-media");
}

function buildSourceIdentity(context, capturedAt = Date.now()) {
  const tab = context?.tab || {};
  const page = context?.page || {};
  const pageUrl = page.page_url || tab.url || "";
  const platform = platformIdentity(pageUrl, page);
  const active = page.active_video || {};
  const pageTitle = String(page.title || tab.title || "").trim();
  const activeCurrentSrc = String(active.current_src || active.currentSrc || active.src || "").trim();
  return {
    tab_id: Number.isFinite(Number(tab.id)) ? Number(tab.id) : null,
    canonical_page_url: canonicalPageUrl(pageUrl),
    platform: platform.platform,
    platform_video_id: platform.platformVideoId,
    BVID: platform.platform === "bilibili" ? platform.platformVideoId : "",
    page_title: pageTitle,
    active_video: { current_src: activeCurrentSrc },
    resource_fingerprint: resourceFingerprint(page, context?.resources || []),
    captured_at: new Date(capturedAt).toISOString()
  };
}

function sourceIdentityKey(identity = {}) {
  return [
    identity.tab_id ?? "",
    identity.canonical_page_url || "",
    identity.platform || "",
    identity.platform_video_id || identity.BVID || "",
    identity.page_title || "",
    identity.active_video?.current_src || "",
    identity.resource_fingerprint || ""
  ].join("\u001f");
}

function sourceContinuityKey(identity = {}) {
  return [
    identity.tab_id ?? "",
    identity.canonical_page_url || "",
    identity.platform || "",
    identity.platform_video_id || identity.BVID || "",
    stableMediaUrl(identity.active_video?.current_src || "")
  ].join("\u001f");
}

function sameSourceIdentity(left, right) {
  if (!left || !right) return false;
  const leftTab = Number(left.tab_id);
  const rightTab = Number(right.tab_id);
  if (Number.isFinite(leftTab) && Number.isFinite(rightTab) && leftTab !== rightTab) return false;
  if (left.canonical_page_url && right.canonical_page_url && left.canonical_page_url !== right.canonical_page_url) return false;
  const leftVideoId = String(left.platform_video_id || left.BVID || "");
  const rightVideoId = String(right.platform_video_id || right.BVID || "");
  if (leftVideoId && rightVideoId && leftVideoId !== rightVideoId) return false;
  const leftSrc = stableMediaUrl(left.active_video?.current_src || "");
  const rightSrc = stableMediaUrl(right.active_video?.current_src || "");
  if (!leftVideoId && !rightVideoId && leftSrc && rightSrc && leftSrc !== rightSrc) return false;
  return Boolean(left.canonical_page_url || right.canonical_page_url || leftVideoId || rightVideoId || leftSrc || rightSrc);
}

function resetSourceState(keepRange = false) {
  if (!keepRange) {
    for (const id of ["learningRangeStart","learningRangeEnd"]) { const field=document.querySelector("#"+id); if(field)field.value=""; }
    const mode=document.querySelector("#learningRangeMode"); if(mode)mode.value="whole";
  }
  progressiveReader.reset();
  preflightReport = null;
  preflightIdentity = null;
  preflightAt = 0;
  preflightFingerprint = "";
  preflightRequest = null;
  activeHandoff = null;
  currentTaskId = "";
  currentTaskMode = "";
  currentTaskContentMode = "";
  quickTranscript = [];
  quickNoteText = "";
  if (els.quickAskConversation) els.quickAskConversation.innerHTML = `<p>${escapeQuickHtml(t("ui_answers_cite_only_subtitle_evidence_from_this_video"))}</p>`;
  if (els.quickAskQuestion) els.quickAskQuestion.value = "";
  if (els.quickResultCard) els.quickResultCard.hidden = true;
  els.openTaskButton.hidden = true;
  els.handoffProgress.hidden = true;
  els.handoffPercent.hidden = true;
  els.handoffProgress.setAttribute("aria-valuenow", "0");
  const progressBar = els.handoffProgress.querySelector("span");
  if (progressBar) progressBar.style.width = "0%";
  els.handoffStatus.textContent = t("ui_choose_a_processing_mode_to_get_started");
  els.sendButtonLabel.textContent = t("sendToClient");
}

function preflightCacheKey(identity = displayedIdentity) {
  return `${sourceContinuityKey(identity)}\u001f${identity?.resource_fingerprint || ""}`;
}

function hasFreshPreflight(identity = displayedIdentity) {
  return Boolean(
    preflightReport
    && preflightIdentity
    && sameSourceIdentity(preflightIdentity, identity)
    && preflightFingerprint === preflightCacheKey(identity)
    && Date.now() - preflightAt < PREFLIGHT_TTL_MS
  );
}

function handoffId(identity = displayedIdentity, range = {}) {
  const sourceKey = sourceContinuityKey(identity);
  const rangeKey = JSON.stringify({start:range.start ?? null,end:range.end ?? null});
  if (activeHandoff?.sourceKey === sourceKey && activeHandoff.rangeKey === rangeKey) return activeHandoff.id;
  const id = `ln-${fnv1a(sourceKey + rangeKey)}-${Date.now().toString(36)}`;
  activeHandoff = { sourceKey, rangeKey, id };
  return id;
}

function mediaCandidates(context = currentContext) {
  return (context?.resources || []).filter(item => {
    const kind = String(item?.kind || "");
    if (SUBTITLE_KIND_RE.test(kind)) return false;
    return MEDIA_KIND_RE.test(kind) || AUDIO_KIND_RE.test(kind) || /\.(?:mp4|m3u8|mpd|m4s|ts)(?:$|[?#])/i.test(String(item?.url || ""));
  });
}

function formatDuration(seconds) {
  const total = Math.round(Number(seconds || 0));
  if (!Number.isFinite(total) || total <= 0) return "--";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remain = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}` : `${minutes}:${String(remain).padStart(2, "0")}`;
}

function explicitIntegrity(report = preflightReport) {
  const raw = report?.integrity || report?.media_integrity || report?.stream_integrity || {};
  const explicit = key => typeof raw[key] === "boolean" ? raw[key] : null;
  return {
    video: explicit("video") ?? explicit("has_video"),
    audio: explicit("audio") ?? explicit("has_audio"),
    subtitle: explicit("subtitle") ?? explicit("has_subtitle")
  };
}

function integrityEvidence(context = currentContext, report = preflightReport) {
  const page = context?.page || {};
  const active = page.active_video || {};
  const candidates = context?.resources || [];
  const explicit = explicitIntegrity(report);
  const videoEvidence = Boolean(active.current_src || active.currentSrc || active.src || active.src_object_video_tracks > 0 || candidates.some(item => {
    const kind = String(item?.kind || "");
    return !AUDIO_KIND_RE.test(kind) && !SUBTITLE_KIND_RE.test(kind) && (MEDIA_KIND_RE.test(kind) || /\.(?:mp4|m3u8|mpd|m4s)(?:$|[?#])/i.test(String(item?.url || "")));
  }));
  const audioEvidence = Boolean(
    active.has_audio === true ||
    Number(active.src_object_audio_tracks || 0) > 0 ||
    Number(active.capture_stream_audio_tracks || 0) > 0 ||
    Number(active.audio_decoded_byte_count || 0) > 0 ||
    candidates.some(item => AUDIO_KIND_RE.test(String(item?.kind || "")) || /^audio\//i.test(String(item?.mime || item?.content_type || "")))
  );
  const subtitleEvidence = Boolean((page.browser_subtitles || []).length || candidates.some(item => SUBTITLE_KIND_RE.test(String(item?.kind || item?.mime || item?.content_type || ""))));
  return {
    video: explicit.video === null ? (videoEvidence ? true : null) : explicit.video,
    audio: explicit.audio === null ? (audioEvidence ? true : null) : explicit.audio,
    subtitle: explicit.subtitle === null ? (subtitleEvidence ? true : null) : explicit.subtitle
  };
}

function setIntegrityItem(kind, value) {
  const item = els.integrityGrid?.querySelector(`[data-kind="${kind}"]`);
  if (!item) return;
  const label = value === true ? t("ui_detected") : value === false ? t("ui_not_found") : t("ui_unconfirmed");
  item.dataset.state = value === true ? "found" : value === false ? "missing" : "unknown";
  const strong = item.querySelector("strong");
  if (strong) strong.textContent = label;
}

function renderContext(message = "") {
  renderSourcePreview();
  const page = currentContext?.page || {};
  const tab = currentContext?.tab || {};
  const active = page.active_video || {};
  const identity = currentContext ? buildSourceIdentity(currentContext) : null;
  const platform = platformIdentity(page.page_url || tab.url || "", page);
  const candidates = mediaCandidates();
  const subtitleReady = hasReliableBrowserSubtitles(currentContext);
  const title = identity?.page_title || t("ui_no_video_page_identified");
  const duration = Number(active.duration || 0);
  const playing = Boolean(active && active.paused === false && (active.src || active.src_object));
  const evidence = integrityEvidence();

  els.platformLabel.textContent = platform.label;
  els.videoTitle.textContent = title;
  els.videoMeta.textContent = identity?.platform_video_id
    ? `${identity.platform_video_id} · ${identity.canonical_page_url}`
    : (identity?.canonical_page_url || t("ui_open_a_video_page_and_start_playback"));
  els.playingBadge.hidden = !playing;
  els.candidateCount.textContent = String(candidates.length);
  els.durationValue.textContent = formatDuration(duration);
  els.estimateValue.textContent = subtitleReady ? t("ui_player_subtitles") : t("ui_platform_lookup_pending");
  setIntegrityItem("video", evidence.video);
  setIntegrityItem("audio", evidence.audio);
  setIntegrityItem("subtitle", evidence.subtitle);
  const subtitleLabel = els.integrityGrid?.querySelector('[data-kind="subtitle"] strong');
  if (subtitleLabel) subtitleLabel.textContent = subtitleReady ? t("ui_transcript_ready") : evidence.subtitle === true ? t("ui_evidence_found") : t("ui_transcript_not_yet_available");
  if (!subtitleReady && page.subtitle_probe?.status === "auth_required") els.estimateValue.textContent = t("ui_sign_in_required");
  else if (!subtitleReady && page.subtitle_probe?.status === "unavailable") els.estimateValue.textContent = t("ui_lookup_failed_refresh_to_retry");

  const hasPage = Boolean(identity?.canonical_page_url && !/^(?:chrome|edge|about):/i.test(identity.canonical_page_url) && !/^https?:\/\/(?:www\.)?bilibili\.com\/?(?:[?#].*)?$/i.test(identity.canonical_page_url));
  const hasMediaEvidence = evidence.video === true || candidates.length > 0 || subtitleReady || (platform.platform === "bilibili" && Boolean(identity?.platform_video_id));
  const alreadySent = Boolean(currentTaskId && activeHandoff?.sourceKey === sourceContinuityKey(identity));
  const needsModel = selectedProcessingMode !== "quick";
  const modelMissing = needsModel && modelReadiness.configured === false;
  const visionUnavailable = selectedProcessingMode === "deep" && modelReadiness.supportsVision === false;
  const readiness = document.querySelector("#modelReadiness");
  if (readiness) {
    readiness.hidden = !clientConnected || !needsModel;
    document.querySelector("#modelReadinessText").textContent = modelMissing
      ? t("ui_no_model_is_configured_save_a_model_in_the_workspace_or_choose")
      : visionUnavailable ? t("model_no_images", { model: modelReadiness.model || "" })
      : modelReadiness.configured ? t("model_ready", { model: modelReadiness.model || t("ui_configured") }) : t("ui_model_status_is_unconfirmed_check_the_connection_in_the_worksp");
    document.querySelector("#configureModelButton").hidden = !modelMissing && !visionUnavailable;
  }
  els.sendButton.disabled = sending || alreadySent || !clientConnected || !hasPage || !hasMediaEvidence || modelMissing || visionUnavailable;
  els.sendButtonLabel.textContent = currentTaskId
    ? (currentTaskMode === "subtitle_only" ? t("ui_processing_started") : t("ui_sent_to_workspace"))
    : selectedProcessingMode === "quick" ? t("ui_extract_transcript")
      : selectedProcessingMode === "study" ? t("ui_generate_text_note") : t("ui_generate_visual_note");
  if (modelMissing && !currentTaskId) els.sendButtonLabel.textContent = t("ui_set_up_a_model_in_the_workspace_first");
  else if (visionUnavailable && !currentTaskId) els.sendButtonLabel.textContent = t("ui_choose_a_vision_model_first");
  if (els.modeDescription) els.modeDescription.textContent = selectedProcessingMode === "quick"
    ? t("ui_reads_existing_subtitles_only_no_video_download_speech_recogni")
    : selectedProcessingMode === "study"
      ? (subtitleReady ? t("ui_subtitles_are_ready_for_the_workspace_text_model_no_video_down") : t("ui_uses_existing_subtitles_first_if_unavailable_confirm_local_spe"))
      : t("ui_downloads_the_video_and_combines_subtitles_with_selected_frame");
  if (els.extensionOptions) els.extensionOptions.hidden = selectedProcessingMode === "quick";
  if (message) {
    els.preflightMessage.textContent = message;
  } else if (!hasPage) {
    els.preflightMessage.textContent = t("ui_switch_to_the_page_playing_your_video");
  } else if (subtitleReady) {
    const elapsed = currentContext?.page?.subtitle_probe?.elapsed_ms;
    const timing = currentContext?.page?.subtitle_probe?.cache_hit ? t("ui_cached") : Number.isFinite(elapsed) ? t("lookup_timing", { seconds: (elapsed / 1000).toFixed(1) }) : "";
    els.preflightMessage.textContent = t("subtitles_ready_count", { count: subtitleCues().length, timing });
  } else if (currentContext?.page?.subtitle_probe?.status === "auth_required") {
    els.preflightMessage.textContent = t("ui_the_subtitle_service_requires_a_valid_bilibili_sign_in_sign_in");
  } else if (selectedProcessingMode === "quick") {
    els.preflightMessage.textContent = t("ui_the_player_has_not_provided_complete_subtitles_the_workspace_w");
  } else if (!hasMediaEvidence) {
    els.preflightMessage.textContent = t("ui_no_player_or_media_candidate_detected_yet_play_a_few_seconds_a");
  } else if (preflightReport?.ready || preflightReport?.downloadable_count > 0) {
    els.preflightMessage.textContent = productMessage(preflightReport.message) || t("ui_source_preflight_passed_ready_to_send_to_the_client");
  } else if (preflightReport) {
    els.preflightMessage.textContent = productMessage(preflightReport.message) || t("ui_media_candidates_found_the_client_will_continue_resolving_them");
  } else {
    els.preflightMessage.textContent = t("ui_video_source_identified_complete_subtitles_are_not_yet_availab");
  }
}

function setConnection(state, title, detail) {
  clientConnected = state === "connected";
  els.connectionCard.dataset.state = state;
  els.connectionTitle.textContent = title;
  els.connectionDetail.textContent = detail;
  renderContext();
}

function setProgress(value, message, state = "active") {
  const progress = Math.max(0, Math.min(100, Math.round(Number(value || 0))));
  els.handoffProgress.hidden = false;
  els.handoffPercent.hidden = false;
  els.handoffProgress.dataset.state = state;
  els.handoffProgress.setAttribute("aria-valuenow", String(progress));
  const bar = els.handoffProgress.querySelector("span");
  if (bar) bar.style.width = `${progress}%`;
  els.handoffPercent.textContent = `${progress}%`;
  els.handoffStatus.textContent = message;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  let timer = 0;
  if (controller) timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, ...(controller ? { signal: controller.signal } : {}) });
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function loadBackendUrl() {
  if (!HAS_EXTENSION_API) return;
  const stored = await chrome.storage.local.get({ backendUrl: DEFAULT_BACKEND_URL, processingMode: "study" });
  backendUrl = normalizedBackendUrl(stored.backendUrl);
  setProcessingMode(stored.processingMode, false);
}

async function checkClient({ quiet = false } = {}) {
  if (connectionRequest) return connectionRequest;
  connectionRequest = (async () => {
    if (!clientConnected && !quiet) setConnection("checking", t("ui_connecting_to_learnnote"), t("ui_looking_for_the_local_workspace"));
    let incompatibleClient = null;
    const probe = async candidate => {
      try {
        const response = await fetchWithTimeout(`${candidate}/health`, {}, HEALTH_TIMEOUT_MS);
        if (!response.ok) return null;
        const health = await response.json();
        const isLearnNote = health.service === "learnnote" || (!health.service && health.task_schema_version && typeof health.local_asr_available === "boolean");
        if (!isLearnNote || !health.app_version || !health.backend_version) return null;
        if (health.protocol_version !== PROTOCOL_VERSION) {
          incompatibleClient ||= { candidate, health };
          return null;
        }
        return { candidate, health };
      } catch { return null; }
    };
    let match = await probe(backendUrl);
    // A task belongs to one local instance. Never open its id against a different library.
    if (!match && !currentTaskId) {
      const candidates = [DEFAULT_BACKEND_URL];
      if (HAS_EXTENSION_API && chrome.tabs?.query) {
        try {
          for (const tab of await chrome.tabs.query({ url: ["http://127.0.0.1/*", "http://localhost/*"] })) {
            try {
              const origin = new URL(tab.url).origin;
              if (LOCAL_BACKEND_RE.test(origin) && !candidates.includes(origin)) candidates.push(origin);
            } catch {}
          }
        } catch {}
      }
      const results = await Promise.all(candidates.filter(value => value !== backendUrl).slice(0, 8).map(probe));
      match = results.find(Boolean);
    }
    if (match) {
      backendUrl = match.candidate;
      modelReadiness = { configured: typeof match.health.llm_model_configured === "boolean" ? match.health.llm_model_configured : null, model: match.health.default_llm_model || "", supportsVision: match.health.default_llm_supports_vision === false ? false : null };
      if (HAS_EXTENSION_API) await chrome.storage.local.set({ backendUrl }).catch(() => {});
      if (els.clientInstallHelp) els.clientInstallHelp.hidden = true;
      setConnection("connected", t("ui_local_workspace_connected"), `LearnNote ${match.health.app_version} · ${backendUrl}`);
      return true;
    }
    modelReadiness = { configured: null, model: "", supportsVision: null };
    if (incompatibleClient) {
      const health = incompatibleClient.health;
      const detectedProtocol = health.protocol_version !== null && health.protocol_version !== undefined && health.protocol_version !== "" && Number.isFinite(Number(health.protocol_version))
        ? health.protocol_version
        : t("ui_unknown");
      const detail = t("incompatible_client_detail", { extension: PROTOCOL_VERSION, version: health.app_version, protocol: detectedProtocol });
      if (els.clientInstallHelp) els.clientInstallHelp.hidden = false;
      setConnection(
        "offline",
        t("incompatible_client_title"),
        detail
      );
      return false;
    }
    if (quiet) { clientConnected = false; renderContext(); return false; }
    if (els.clientInstallHelp) els.clientInstallHelp.hidden = false;
    setConnection("offline", currentTaskId ? t("ui_the_workspace_for_this_task_is_disconnected") : t("ui_local_workspace_is_not_running"), currentTaskId
      ? t("reopen_workspace", { url: backendUrl })
      : t("ui_click_open_workspace_to_launch_the_installed_learnnote_app_no_"));
    return false;
  })();
  try { return await connectionRequest; }
  finally { connectionRequest = null; }
}

async function collectContext(force = true, targetTabId = null) {
  if (!HAS_EXTENSION_API) {
    renderContext(t("ui_use_the_learnnote_extension_in_chrome_or_edge_to_identify_the_"));
    return null;
  }
  const requestedTabId = targetTabId ?? currentContext?.tab?.id ?? null;
  if (collectRequest?.targetTabId === requestedTabId) return collectRequest.promise;
  const generation = ++contextGeneration;
  els.refreshButton.disabled = true;
  const promise = (async () => {
   try {
    const response = await withTimeout(chrome.runtime.sendMessage({
      type: "get-current-context",
      targetTabId: requestedTabId,
      useCached: !force
    }), REQUEST_TIMEOUT_MS, t("ui_reading_the_current_page"));
    if (generation !== contextGeneration) return currentContext;
    if (response?.error) throw new Error(productMessage(response.error));
    const next = {
      tab: response?.tab || {},
      page: response?.page || {},
      resources: Array.isArray(response?.resources) ? response.resources : []
    };
    const nextIdentity = buildSourceIdentity(next);
    const changed = displayedIdentity && !sameSourceIdentity(displayedIdentity, nextIdentity);
    currentContext = next;
    displayedIdentity = nextIdentity;
    if (changed) {
      resetSourceState();
    }
    renderContext(changed ? t("ui_the_page_or_video_changed_old_preflight_data_was_cleared_revie") : "");
    return next;
  } catch (error) {
    els.preflightMessage.dataset.state = "error";
    renderContext(t("identification_failed", { detail: productMessage(error?.message) || t("ui_refresh_the_page_and_try_again") }));
    return null;
  } finally {
    if (generation === contextGeneration) {
      collectRequest = null;
      els.refreshButton.disabled = false;
    }
  }
  })();
  collectRequest = { targetTabId: requestedTabId, promise };
  return promise;
}

async function runPreflight(identity = displayedIdentity) {
  if (!clientConnected || !currentContext || !identity) return null;
  if (selectedProcessingMode === "quick" || (selectedProcessingMode === "study" && hasReliableBrowserSubtitles(currentContext))) return null;
  const permissionEpoch = sitePermissionEpoch;
  const candidates = mediaCandidates(currentContext);
  if (!candidates.length && !currentContext.page?.active_video) return null;
  if (!(await sitePermissionGranted(identity.canonical_page_url))) {
    if (sameSourceIdentity(identity, displayedIdentity)) {
      els.preflightMessage.dataset.state = "info";
      renderContext(t("ui_click_send_and_allow_this_site_first_media_candidates_and_cook"));
    }
    return null;
  }
  if (permissionEpoch !== sitePermissionEpoch || !sameSourceIdentity(identity, displayedIdentity)) return null;
  if (hasFreshPreflight(identity)) return preflightReport;
  const requestKey = preflightCacheKey(identity);
  if (preflightRequest?.key === requestKey) return preflightRequest.promise;
  const request = { key: requestKey, promise: null };
  preflightRequest = request;
  request.promise = (async () => {
   try {
    const response = await withTimeout(chrome.runtime.sendMessage({
      type: "preflight-current-page",
      backendUrl,
      targetTabId: identity.tab_id,
      page: currentContext.page,
      resources: candidates,
      sourceIdentity: identity,
      probeLimit: 3
    }), REQUEST_TIMEOUT_MS, t("ui_media_preflight"));
    if (response?.error) throw new Error(productMessage(response.error));
    if (permissionEpoch !== sitePermissionEpoch || !sameSourceIdentity(identity, displayedIdentity)) return null;
    preflightReport = response?.report || null;
    preflightIdentity = identity;
    preflightAt = Date.now();
    preflightFingerprint = requestKey;
    els.preflightMessage.dataset.state = preflightReport?.ready ? "ready" : "info";
    renderContext();
    return preflightReport;
  } catch (error) {
    if (permissionEpoch === sitePermissionEpoch && sameSourceIdentity(identity, displayedIdentity)) {
      els.preflightMessage.dataset.state = "error";
      renderContext(t("preflight_unavailable", { detail: productMessage(error?.message) || t("ui_the_client_will_continue_checking") }));
    }
    return null;
  } finally {
    if (preflightRequest === request) preflightRequest = null;
  }
  })();
  return request.promise;
}

async function refreshAndPreflight({ force = true } = {}) {
  els.preflightMessage.dataset.state = "info";
  els.preflightMessage.textContent = t("ui_reading_available_subtitles");
  const context = await collectContext(force);
  if (context && clientConnected) await runPreflight(displayedIdentity);
  return context;
}

function pageSwitchMessage() {
  return t("ui_the_page_or_video_changed_old_preflight_results_were_discarded");
}

function learningRange(context = currentContext) {
  const mode = document.querySelector("#learningRangeMode")?.value || "custom";
  const duration = Number(context?.page?.active_video?.duration || 0), current = Number(context?.page?.active_video?.current_time);
  if (/^current(5|15|30)$/.test(mode)) {
    if (!Number.isFinite(current) || current < 0 || (duration > 0 && current >= duration)) throw new Error(t("range_position_unavailable"));
    return { start:current, end:Math.min(duration || Infinity,current+Number(mode.slice(7))*60) };
  }
  if (mode === "chapter") {
    const chapter = (context?.page?.chapters || []).filter(item => Number.isFinite(Number(item.start)) && Number.isFinite(Number(item.end)) && Number(item.start) >= 0 && Number(item.end) > Number(item.start) && Number(item.start) <= current && current < Number(item.end) && (!duration || Number(item.end) <= duration+0.1)).sort((a,b)=>Number(b.start)-Number(a.start))[0];
    if (!chapter) throw new Error(t("range_chapter_unavailable"));
    return {start:Number(chapter.start),end:Number(chapter.end)};
  }
  const startValue=document.querySelector("#learningRangeStart")?.value || "", endValue=document.querySelector("#learningRangeEnd")?.value || "";
  if (!startValue && !endValue) return {};
  const start=Number(startValue || 0), end=Number(endValue || duration);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start || (duration > 0 && end > duration)) throw new Error(t("ui_invalid_range_the_end_time_must_be_greater_than_the_start_time"));
  return {start,end};
}

async function updateLearningRangeMode() {
  resetSourceState(true);
  const mode=document.querySelector("#learningRangeMode")?.value || "whole";
  const hint=document.querySelector("#learningChapterHint"), status=document.querySelector("#learningRangeStatus"), start=document.querySelector("#learningRangeStart"), end=document.querySelector("#learningRangeEnd");
  if(mode === "whole") { if(start)start.value="";if(end)end.value="";if(hint)hint.textContent="";return; }
  if(mode === "custom")return;
  const expected=displayedIdentity;
  try {
    const fresh=await collectContext(true);
    if(!fresh || !sameSourceIdentity(expected,buildSourceIdentity(fresh)))throw new Error(pageSwitchMessage());
    const range=learningRange(fresh);
    if(start)start.value=String(range.start);if(end)end.value=String(range.end);
    if(hint)hint.textContent=t("range_selected_bounds",{start:range.start,end:range.end});if(status)status.textContent="";
  } catch(error) {if(status)status.textContent=productMessage(error.message);}
}

function sitePermissionPattern(pageUrl = "") {
  try {
    const url = new URL(pageUrl);
    if (!["http:", "https:"].includes(url.protocol) || !url.host) return "";
    return `${url.protocol}//${url.hostname}/*`;
  } catch {
    return "";
  }
}

function permissionPatternMatchesPage(pattern = "", pageUrl = "") {
  const requested = String(pattern || "").trim().toLowerCase();
  const current = sitePermissionPattern(pageUrl).toLowerCase();
  if (!requested || !current) return false;
  if (requested === current) return true;
  const match = /^(https?):\/\/([^/]+)\/\*$/i.exec(requested);
  if (!match) return false;
  let page;
  try { page = new URL(pageUrl); } catch { return false; }
  if (page.protocol !== `${match[1].toLowerCase()}:`) return false;
  const host = match[2].toLowerCase();
  if (host === "*") return true;
  if (host.startsWith("*.")) {
    const suffix = host.slice(2);
    return page.hostname.toLowerCase() === suffix || page.hostname.toLowerCase().endsWith(`.${suffix}`);
  }
  return page.hostname.toLowerCase() === host;
}

async function sitePermissionGranted(pageUrl = "") {
  const origin = sitePermissionPattern(pageUrl);
  if (!origin || !globalThis.chrome?.permissions?.contains) return true;
  try {
    return await chrome.permissions.contains({ origins: [origin] });
  } catch {
    return false;
  }
}

function clearPageContextAfterPermissionRevocation(origin = "") {
  const pageUrl = displayedIdentity?.canonical_page_url || currentContext?.page?.page_url || currentContext?.tab?.url || "";
  if (!permissionPatternMatchesPage(origin, pageUrl)) return false;
  sitePermissionEpoch += 1;
  contextGeneration += 1;
  collectRequest = null;
  els.refreshButton.disabled = false;
  currentContext = null;
  displayedIdentity = null;
  preflightReport = null;
  preflightIdentity = null;
  preflightAt = 0;
  preflightFingerprint = "";
  preflightRequest = null;
  progressiveReader.reset();
  quickTranscript = [];
  quickNoteText = "";
  if (els.quickAskConversation) els.quickAskConversation.innerHTML = `<p>${escapeQuickHtml(t("ui_answers_cite_only_subtitle_evidence_from_this_video"))}</p>`;
  if (els.quickAskQuestion) els.quickAskQuestion.value = "";
  if (els.quickResultCard) els.quickResultCard.hidden = true;
  if (!currentTaskId) resetSourceState();
  else {
    els.openTaskButton.hidden = false;
    els.handoffStatus.textContent = t("ui_permission_revoked_tasks_already_sent_to_this_computer_can_sti");
  }
  renderContext(currentTaskId
    ? t("ui_site_permission_revoked_page_evidence_and_capture_caches_were_")
    : t("ui_site_permission_revoked_page_evidence_and_capture_caches_were__2")
  );
  return true;
}

function sitePermissionLabel(pattern = "") {
  return String(pattern).replace(/:\/\/([^/]+)\/\*$/, "$1");
}

async function loadSitePermissions() {
  const list = els.permissionList;
  if (!list) return;
  list.replaceChildren();
  if (!globalThis.chrome?.permissions?.getAll) {
    list.textContent = t("ui_this_environment_cannot_list_site_permissions");
    return;
  }
  try {
    const granted = await chrome.permissions.getAll();
    const origins = (granted?.origins || [])
      .map(value => String(value || ""))
      .filter(value => /^https?:\/\/[^/]+\/\*$/i.test(value));
    if (!origins.length) {
      list.textContent = t("ui_no_additional_sites_authorized_local_workspace_access_does_not");
      return;
    }
    for (const origin of origins.sort()) {
      const row = document.createElement("article");
      row.className = "permission-item";
      const label = document.createElement("strong");
      label.textContent = sitePermissionLabel(origin);
      const detail = document.createElement("small");
      detail.textContent = t("site_permission_data_flow");
      const revoke = document.createElement("button");
      revoke.type = "button";
      revoke.className = "secondary-button compact-button";
      revoke.textContent = t("ui_revoke");
      revoke.setAttribute("aria-label", t("revoke_site_label", { site: sitePermissionLabel(origin) }));
      revoke.onclick = async () => {
        revoke.disabled = true;
        if (els.permissionStatus) els.permissionStatus.textContent = t("revoking_site", { site: sitePermissionLabel(origin) });
        try {
          const removed = await chrome.permissions.remove({ origins: [origin] });
          if (!removed) throw new Error(t("ui_the_browser_did_not_accept_the_revocation_request"));
          clearPageContextAfterPermissionRevocation(origin);
          try {
            await chrome.runtime.sendMessage({ type: "revoke-site-permission", origin });
          } catch {
            // The permission is already revoked; cache cleanup is best effort.
          }
          if (els.permissionStatus) els.permissionStatus.textContent = t("site_revoked", { site: sitePermissionLabel(origin) });
          await loadSitePermissions();
        } catch (error) {
          revoke.disabled = false;
          if (els.permissionStatus) els.permissionStatus.textContent = productMessage(error?.message) || t("ui_revocation_failed_try_again_in_the_browser_extension_settings");
        }
      };
      row.append(label, detail, revoke);
      list.append(row);
    }
  } catch (error) {
    list.textContent = t("permissions_unavailable", { detail: productMessage(error?.message) || t("ui_try_again_later") });
  }
}

async function ensureSitePermission(pageUrl = "") {
  if (!globalThis.chrome?.permissions?.request) return true;
  const origin = sitePermissionPattern(pageUrl);
  if (!origin) return true;
  if (await sitePermissionGranted(pageUrl)) return true;
  if (els.permissionDetails) els.permissionDetails.open = true;
  if (els.permissionStatus) {
    els.permissionStatus.textContent = t("site_authorization_pending", { site: sitePermissionLabel(origin) });
  }
  const granted = await chrome.permissions.request({ origins: [origin] });
  await loadSitePermissions();
  if (els.permissionStatus) {
    els.permissionStatus.textContent = granted
      ? t("site_authorization_granted", { site: sitePermissionLabel(origin) })
      : t("site_authorization_denied", { site: sitePermissionLabel(origin) });
  }
  return granted;
}

async function sendToClient(modeOverride = "") {
  if (sending || !displayedIdentity) return false;
  if (typeof modeOverride !== "string") modeOverride = "";
  const requestedMode = modeOverride === "video" ? "deep" : (modeOverride || selectedProcessingMode);
  const selectedOptions = processingOptions(requestedMode);
  let selectedRange;
  try {
    selectedRange = learningRange();
  } catch (error) {
    const status = document.querySelector("#learningRangeStatus");
    if (status) status.textContent = productMessage(error.message);
    return false;
  }
  const permissionEpoch = sitePermissionEpoch;
  sending = true;
  document.querySelectorAll?.("[data-processing-mode]").forEach(button => { button.disabled = true; });
  els.sendButton.disabled = true;
  els.sendButton.setAttribute("aria-busy", "true");
  els.sendButtonLabel.textContent = t("ui_sending");
  els.openTaskButton.hidden = true;
  const expectedIdentity = displayedIdentity;
  try {
    if (/^https?:\/\/(?:www\.)?bilibili\.com\/?(?:[?#].*)?$/i.test(expectedIdentity.canonical_page_url || "")) {
      throw new Error(t("ui_open_a_specific_video_first_homepage_recommendation_previews_c"));
    }
    setProgress(8, t("ui_connecting_to_learnnote_2"));
    if (!(await checkClient())) throw new Error(t("ui_the_client_is_not_running_open_learnnote_first"));
    if (requestedMode !== "quick" && modelReadiness.configured === false) throw new Error(t("ui_no_usable_model_is_configured_set_one_up_or_choose_transcript_"));
    if (requestedMode === "deep" && modelReadiness.supportsVision === false) throw new Error(t("ui_the_model_does_not_support_images_choose_a_vision_model_or_a_t"));
    if (!(await ensureSitePermission(expectedIdentity.canonical_page_url))) throw new Error(t("ui_this_site_was_not_authorized_no_task_was_created_click_send_ag"));
    if (permissionEpoch !== sitePermissionEpoch) throw new Error(t("ui_site_permission_was_revoked_sending_stopped_confirm_again_befo"));

    setProgress(24, t("ui_reading_the_current_page_again"));
    const fresh = await collectContext(true);
    if (!fresh) throw new Error(t("ui_unable_to_read_the_current_page"));
    if (permissionEpoch !== sitePermissionEpoch || !(await sitePermissionGranted(expectedIdentity.canonical_page_url))) {
      throw new Error(t("ui_site_permission_was_revoked_sending_stopped_authorize_and_iden"));
    }
    const freshIdentity = buildSourceIdentity(fresh);
    if (!sameSourceIdentity(expectedIdentity, freshIdentity)) {
      displayedIdentity = freshIdentity;
      resetSourceState();
      renderContext(pageSwitchMessage());
      setProgress(0, pageSwitchMessage(), "error");
      return false;
    }

    selectedRange = learningRange(fresh);
    const taskBackendUrl = backendUrl;
    const canReadCreatedTask = () => permissionEpoch === sitePermissionEpoch && taskBackendUrl === backendUrl && sameSourceIdentity(freshIdentity, displayedIdentity);
    const quick = requestedMode !== "deep" && hasReliableBrowserSubtitles(fresh);
    currentTaskContentMode = selectedOptions.content_mode;
    if (quick) {
      currentTaskMode = "subtitle_only";
      setProgress(48, t("ui_complete_subtitles_found_skipping_media_preflight_and_video_pr"));
      if (permissionEpoch !== sitePermissionEpoch || !(await sitePermissionGranted(expectedIdentity.canonical_page_url))) {
        throw new Error(t("ui_site_permission_was_revoked_the_transcript_task_was_not_sent_a"));
      }
      const response = await withTimeout(chrome.runtime.sendMessage({
        type: "start-current-task",
        backendUrl: taskBackendUrl,
        targetTabId: freshIdentity.tab_id,
        page: fresh.page,
        resources: [],
        sourceIdentity: freshIdentity,
        handoffId: handoffId(freshIdentity, selectedRange),
        defer: false,
        mode: "subtitle_only",
        learning_range: selectedRange,
        options: selectedOptions
      }), REQUEST_TIMEOUT_MS, t("ui_creating_transcript_task"));
      if (!canReadCreatedTask()) return false;
      if (response?.error) throw new Error(productMessage(response.error));
      currentTaskId = String(response?.task_id || "");
      if (!currentTaskId) throw new Error(t("ui_the_client_did_not_confirm_the_transcript_task"));
      els.openTaskButton.hidden = false;
      showQuickResult(currentTaskContentMode === "subtitles" ? t("ui_saving_the_original_transcript") : t("ui_generating_with_the_text_model"));
      setQuickTab(currentTaskContentMode === "subtitles" ? "transcript" : "summary");
      startProgressiveReading();
      setProgress(72, currentTaskContentMode === "subtitles" ? t("ui_subtitles_sent_to_the_local_service_saving_the_original_transc") : t("ui_subtitles_sent_to_the_text_model_generating_a_note"));
      return true;
    }

    setProgress(48, requestedMode === "quick" ? t("ui_preparing_platform_subtitle_lookup_no_video_download") : (hasFreshPreflight(freshIdentity) ? t("ui_reused_the_recent_source_check") : t("ui_checking_the_video_source")));
    if (requestedMode !== "quick" && !hasFreshPreflight(freshIdentity)) await runPreflight(freshIdentity);
    if (!sameSourceIdentity(freshIdentity, displayedIdentity)) {
      setProgress(0, pageSwitchMessage(), "error");
      return false;
    }

    if (permissionEpoch !== sitePermissionEpoch || !(await sitePermissionGranted(expectedIdentity.canonical_page_url))) {
      throw new Error(t("ui_site_permission_was_revoked_the_task_was_not_sent_authorize_an"));
    }

    currentTaskMode = "video";
    const videoHandoffId = requestedMode === "deep" && activeHandoff?.sourceKey === sourceContinuityKey(freshIdentity)
      ? (activeHandoff = null, handoffId(freshIdentity, selectedRange))
      : handoffId(freshIdentity, selectedRange);
    setProgress(76, t("ui_sending_the_video_source_to_the_client"));
    const response = await withTimeout(chrome.runtime.sendMessage({
      type: "start-current-task",
      backendUrl: taskBackendUrl,
      targetTabId: freshIdentity.tab_id,
      page: fresh.page,
      resources: requestedMode === "quick" ? [] : mediaCandidates(fresh),
      pagePreflightReport: sameSourceIdentity(preflightIdentity, freshIdentity) ? preflightReport : null,
      sourceIdentity: freshIdentity,
      handoffId: videoHandoffId,
      defer: true,
      mode: "video",
      learning_range: selectedRange,
      options: selectedOptions
    }), REQUEST_TIMEOUT_MS, t("sendToClient"));
    if (!canReadCreatedTask()) return false;
    if (response?.error) throw new Error(productMessage(response.error));
    currentTaskId = String(response?.task_id || "");
    if (!currentTaskId) throw new Error(t("ui_the_client_did_not_confirm_task_creation_try_again"));
    setProgress(92, response?.deduplicated ? t("ui_task_already_exists_opening_the_client") : t("ui_task_created_opening_the_client"));
    els.openTaskButton.hidden = !currentTaskId;
    startProgressiveReading();
    const opened = await openClient("task", currentTaskId, "note");
    setProgress(100, opened ? t("ui_sent_to_the_workspace_review_and_confirm_to_start_processing") : t("ui_task_created_use_the_button_below_to_open_it_and_confirm_proce"), "success");
    return true;
  } catch (error) {
    setProgress(Number(els.handoffProgress.getAttribute("aria-valuenow") || 0), productMessage(error?.message) || t("ui_sending_failed_try_again"), "error");
    return false;
  } finally {
    sending = false;
    document.querySelectorAll?.("[data-processing-mode]").forEach(button => { button.disabled = false; });
    els.sendButton.setAttribute("aria-busy", "false");
    els.sendButtonLabel.textContent = currentTaskMode === "subtitle_only"
      ? (currentTaskId ? t("ui_transcript_processing_started") : t("ui_retry_transcript_processing"))
      : (currentTaskId ? t("ui_sent_to_client") : t("ui_retry_sending"));
    const preservedMessage = els.preflightMessage.textContent;
    renderContext(preservedMessage);
  }
}

function clientUrl(view = "workspace", taskId = "", tab = "note") {
  const url = new URL(`${backendUrl}/`);
  if (view === "settings") url.hash = "settings";
  else if (taskId) url.hash = `task/${encodeURIComponent(taskId)}${tab !== "note" ? `?tab=${encodeURIComponent(tab)}` : ""}`;
  else if (view === "diagnostics") url.hash = "diagnostics";
  return url.href;
}

async function openClient(view = "workspace", taskId = "", tab = "note") {
  if (clientOpenRequest) return clientOpenRequest;
  els.openClientButton.disabled = true;
  els.openClientButton.setAttribute("aria-busy", "true");
  els.openClientButton.textContent = t("ui_opening");
  if (els.clientInstallHelp) els.clientInstallHelp.hidden = true;
  clientOpenRequest = openClientNow(view, taskId, tab);
  try { return await clientOpenRequest; }
  finally {
    clientOpenRequest = null;
    els.openClientButton.disabled = false;
    els.openClientButton.setAttribute("aria-busy", "false");
    els.openClientButton.textContent = t("openClient");
  }
}

async function focusClientWindow(view, taskId, tab) {
  // Share the background worker's short-lived pairing cache. Re-pair once
  // after a server restart instead of dropping the native focus on a 401.
  for (let attempt = 0; attempt < 2; attempt++) {
    const headers = { "Content-Type": "application/json" };
    if (HAS_EXTENSION_API) {
      const stored = await chrome.storage.local.get({ pairingTokens: {} });
      let pair = stored.pairingTokens?.[backendUrl];
      if (attempt || !pair || Number(pair.expiresAt || 0) <= Date.now() + 15000) {
        const reply = await fetchWithTimeout(`${backendUrl}/api/pairing/issue`, { redirect: "error" }, HEALTH_TIMEOUT_MS);
        const payload = reply.ok ? await reply.json() : null;
        if (payload?.token) {
          pair = { token: String(payload.token), expiresAt: Number(payload.expires_at || 0) * 1000 };
          await chrome.storage.local.set({ pairingTokens: { ...stored.pairingTokens, [backendUrl]: pair } });
        }
      }
      if (pair?.token) headers["X-LearnNote-Pairing"] = pair.token;
    }
    const response = await fetchWithTimeout(`${backendUrl}/api/desktop/focus`, {
      method: "POST", redirect: "error", headers, body: JSON.stringify({ view, task_id: taskId, tab })
    }, HEALTH_TIMEOUT_MS);
    if (response.status === 401 && attempt === 0 && HAS_EXTENSION_API) continue;
    return response.ok ? await response.json() : null;
  }
}

async function openClientNow(view, taskId, tab) {
  let launched = false;
  if (!await checkClient()) {
    setConnection("launching", t("ui_starting_learnnote"), t("ui_if_prompted_by_your_browser_confirm_opening_learnnote_the_work"));
    els.openClientButton.textContent = t("ui_waiting_for_the_client_to_start");
    try {
      suppressTabActivationUntil = Date.now() + CLIENT_START_TIMEOUT_MS + HEALTH_TIMEOUT_MS * 2;
      const launchUrl = `learnnote://open?port=${new URL(backendUrl).port || "8765"}`;
      if (HAS_EXTENSION_API && chrome.tabs?.create) await chrome.tabs.create({url: launchUrl});
      else window.open?.(launchUrl, "_blank");
      launched = true;
    } catch {
      suppressTabActivationUntil = 0;
      if (els.clientInstallHelp) els.clientInstallHelp.hidden = false;
      setConnection("offline", t("ui_unable_to_start_the_client"), t("ui_allow_the_browser_to_open_learnnote_install_the_client_first_o"));
      return false;
    }
    const deadline = Date.now() + CLIENT_START_TIMEOUT_MS;
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      if (await checkClient({ quiet: true })) break;
    }
    if (!clientConnected) {
      suppressTabActivationUntil = 0;
      if (els.clientInstallHelp) els.clientInstallHelp.hidden = false;
      setConnection("offline", t("ui_no_response_from_the_client_yet"), t("ui_the_app_may_be_missing_waiting_for_browser_confirmation_or_sti"));
      return false;
    }
  }
  // Prefer the native window. Headless/source servers retain the browser fallback.
  for (let attempt = 0; attempt < (launched ? 6 : 1); attempt++) {
    try {
      const result = await focusClientWindow(view, taskId, tab);
      if (result?.ok === true && result?.focused === true) {
        suppressTabActivationUntil = Date.now() + CLIENT_TAB_ACTIVATION_SUPPRESS_MS;
        return true;
      }
    } catch { /* Older clients may not expose native focus. */ }
    if (launched && attempt < 5) await new Promise(resolve => setTimeout(resolve, 250));
  }
  const targetUrl = clientUrl(view, taskId, tab);
  try {
    if (!HAS_EXTENSION_API || !chrome.tabs?.create) throw new Error("extension API unavailable");
    suppressTabActivationUntil = Date.now() + CLIENT_TAB_ACTIVATION_SUPPRESS_MS;
    const tabs = await chrome.tabs.query({url: `${backendUrl}/*`});
    const existing = tabs.find(item => {
      try { const url = new URL(item.url); return url.origin === backendUrl && ["/", "/index.html"].includes(url.pathname); }
      catch { return false; }
    });
    if (existing && chrome.tabs.update) {
      const destination = new URL(existing.url);
      if (view !== "workspace" || taskId) destination.hash = new URL(targetUrl).hash;
      await chrome.tabs.update(existing.id, { url: destination.href, active: true });
      if (existing.windowId !== undefined) await chrome.windows?.update?.(existing.windowId, { focused: true });
    } else await chrome.tabs.create({url: targetUrl});
    return true;
  } catch {
    return Boolean(window.open?.(targetUrl, "_blank", "noopener"));
  }
}

function scheduleRefresh(reason = "media", targetTabId = null) {
  if (sending) return;
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(async () => {
    refreshTimer = 0;
    const previous = displayedIdentity;
    const context = await collectContext(reason === "tab-activated", targetTabId);
    if (context && previous && !sameSourceIdentity(previous, displayedIdentity)) {
      els.handoffStatus.textContent = t("ui_new_playback_content_identified");
    }
  }, PASSIVE_REFRESH_DELAY_MS);
}

function bindEvents() {
  els.permissionDetails?.addEventListener("toggle", () => {
    if (els.permissionDetails.open) loadSitePermissions();
  });
  els.refreshButton?.addEventListener("click", async () => {
    await checkClient();
    return refreshAndPreflight({ force: true });
  });
  els.sendButton?.addEventListener("click", () => sendToClient());
  els.quickDeepButton?.addEventListener("click", () => {
    document.querySelector?.('[data-processing-mode="study"]')?.scrollIntoView?.({ block: "center", behavior: "auto" });
    document.querySelector?.('[data-processing-mode="study"]')?.focus?.();
  });
  document.querySelectorAll?.("[data-processing-mode]").forEach(button => {
    button.addEventListener("click", () => setProcessingMode(button.dataset.processingMode || "study"));
    button.addEventListener("keydown", event => {
      if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const modes = ["quick", "study", "deep"];
      const delta = event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : -1;
      const next = modes[(modes.indexOf(selectedProcessingMode) + delta + modes.length) % modes.length];
      setProcessingMode(next);
      document.querySelector?.(`[data-processing-mode="${next}"]`)?.focus?.();
    });
  });
  els.openClientButton?.addEventListener("click", () => openClient("workspace"));
  els.openClientBrand?.addEventListener("click", event => {
    event.preventDefault();
    openClient("workspace");
  });
  els.openTaskButton?.addEventListener("click", () => openClient("task", currentTaskId, "note"));
  document.querySelectorAll?.("[data-quick-tab]").forEach(button => {
    button.addEventListener("click", () => setQuickTab(button.dataset.quickTab || "summary"));
  });
  els.quickAskForm?.addEventListener("submit", async event => {
    event.preventDefault();
    const question = String(els.quickAskQuestion?.value || "").trim();
    if (!question || !currentTaskId || !els.quickAskConversation || quickQuestionPending) return;
    quickQuestionPending = true;
    const taskId = currentTaskId;
    const sourceKey = sourceContinuityKey(displayedIdentity);
    const isCurrent = () => taskId === currentTaskId && sourceKey === sourceContinuityKey(displayedIdentity);
    const submit = els.quickAskForm.querySelector('[type="submit"]');
    if (submit) submit.disabled = true;
    els.quickAskForm.setAttribute("aria-busy", "true");
    const entry = document.createElement?.("article");
    if (entry) {
      entry.innerHTML = `<strong>${escapeQuickHtml(t("ui_you"))}</strong><p>${escapeQuickHtml(question)}</p>`;
      els.quickAskConversation.appendChild(entry);
    }
    try {
      const response = await fetchWithTimeout(`${backendUrl}/api/tasks/${encodeURIComponent(taskId)}/qa`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question })
      });
      if (!response.ok) throw new Error(t("question_http_failed", { status: response.status }));
      const result = await response.json();
      if (!isCurrent()) return;
      const answer = document.createElement?.("article");
      if (answer) {
        answer.innerHTML = `<strong>LearnNote</strong>${renderQuickMarkdown(result?.answer || t("ui_no_subtitle_evidence_was_found_to_cite"))}`;
        els.quickAskConversation.appendChild(answer);
      }
      if (els.quickAskQuestion?.value.trim() === question) els.quickAskQuestion.value = "";
    } catch (error) {
      if (!isCurrent()) return;
      const answer = document.createElement?.("article");
      if (answer) {
        answer.innerHTML = `<strong>${escapeQuickHtml(t("ui_notice"))}</strong><p>${escapeQuickHtml(productMessage(error?.message) || t("ui_question_failed"))}</p>`;
        els.quickAskConversation.appendChild(answer);
      }
    } finally {
      quickQuestionPending = false;
      if (submit) submit.disabled = false;
      els.quickAskForm.setAttribute("aria-busy", "false");
    }
  });
  document.querySelectorAll("[data-client-view]").forEach(button => {
    button.addEventListener("click", () => openClient(button.dataset.clientView || "workspace", currentTaskId, button.dataset.clientView === "diagnostics" && currentTaskId ? "diagnostics" : "note"));
  });
  if (HAS_EXTENSION_API) chrome.runtime?.onMessage?.addListener?.(message => {
    if (message?.type === "site-permission-revoked") {
      clearPageContextAfterPermissionRevocation(message.origin);
      loadSitePermissions();
      return;
    }
    if (message?.type !== "current-context-updated") return;
    if (message.reason === "tab-activated" && chrome.tabs?.get) {
      const generation = ++activationGeneration;
      chrome.tabs.get(message.tabId).then(tab => {
        if (generation !== activationGeneration) return;
        try {
          const url = new URL(tab.url);
          if (url.protocol === "learnnote:" || LOCAL_BACKEND_RE.test(url.origin)) return;
        } catch { return; }
        scheduleRefresh("tab-activated", message.tabId);
      }).catch(() => {});
      return;
    }
    if (message.reason === "tab-activated" && Date.now() < suppressTabActivationUntil) return;
    if (message.reason !== "tab-activated" && displayedIdentity?.tab_id !== null && message.tabId !== displayedIdentity?.tab_id) return;
    scheduleRefresh(message.reason || "media", message.reason === "tab-activated" ? message.tabId : null);
  });
  window.addEventListener?.("focus", () => checkClient());
}

function bindProductActions(){
  document.querySelector("#learningRangeMode")?.addEventListener?.("change",updateLearningRangeMode);
  for(const id of ["learningRangeStart","learningRangeEnd"])document.querySelector("#"+id)?.addEventListener?.("input",()=>{const mode=document.querySelector("#learningRangeMode");if(mode)mode.value="custom";resetSourceState(true);});
  const rangeEndButton = document.querySelector("#useCurrentPositionAsRangeEnd");
  rangeEndButton?.addEventListener?.("click", async () => {
    const expected=displayedIdentity,fresh=await collectContext(true);
    if(!fresh || !sameSourceIdentity(expected,buildSourceIdentity(fresh)))return;
    const mode=document.querySelector("#learningRangeMode");if(mode)mode.value="custom";
    const current = Number(currentContext?.page?.active_video?.current_time || 0);
    const status = document.querySelector("#learningRangeStatus");
    if (!Number.isFinite(current) || current <= 0) {
      if (status) status.textContent = t("ui_the_current_playback_position_is_unavailable_play_the_video_fo");
      return;
    }
    const end = Math.floor(current);
    const input = document.querySelector("#learningRangeEnd");
    if (input) input.value = String(end);
    if (status) status.textContent = t("range_end_filled", { seconds: end });
  });
  const find=id=>document.querySelector?.("#"+id);
  find("subtitleSearch")?.addEventListener?.("input",renderSourcePreview);
  find("copyQuickSummary")?.addEventListener?.("click",async()=>{try{if(!quickNoteText)throw new Error(t("ui_the_summary_is_not_ready_yet"));await navigator.clipboard.writeText(quickNoteText);els.quickResultStatus.textContent=t("ui_summary_copied");}catch(e){els.quickResultStatus.textContent=productMessage(e.message);}});
  find("saveQuickSummary")?.addEventListener?.("click",()=>{if(quickNoteText)downloadResult(quickNoteText,"LearnNote-summary.md","text/markdown;charset=utf-8");});
  find("saveQuickSubtitles")?.addEventListener?.("click",()=>{if(quickTranscript.length)downloadResult(subtitleSrt(quickTranscript),"LearnNote-subtitles.srt","text/plain;charset=utf-8");});
  find("useClientPreferences")?.addEventListener?.("click",async()=>{const status=find("extensionOptionsStatus");try{const response=await fetchWithTimeout(`${backendUrl}/api/preferences`);if(!response.ok)throw new Error(t("ui_connect_to_the_client_first"));const p=(await response.json()).task_options||{};for(const [id,key] of [["extensionStyle","note_style"],["extensionTemplate","note_template"]]){const el=find(id);if(el&&[...el.options].some(o=>o.value===p[key]))el.value=p[key];}if(find("extensionPrompt"))find("extensionPrompt").value=p.note_profile_prompt||"";if(status)status.textContent=t("ui_loaded_the_client_note_style_format_and_additional_instruction");}catch(e){if(status)status.textContent=productMessage(e.message);}});
}
async function initialize() {
  globalThis.LearnNoteI18n?.apply?.(document);
  bindEvents();
  bindProductActions();
  await loadSitePermissions();
  await loadBackendUrl();
  // Reading platform captions does not depend on finding the local client.
  const [, context] = await Promise.all([checkClient(), collectContext(true)]);
  if (context && clientConnected) await runPreflight(displayedIdentity);
}

initialize();

globalThis.__learnnoteSidepanel = {
  canonicalPageUrl,
  platformIdentity,
  resourceFingerprint,
  buildSourceIdentity,
  hasReliableBrowserSubtitles,
  processingOptions,
  setProcessingMode,
  subtitleSrt,
  renderQuickMarkdown,
  renderQuickTranscript,
  groupSubtitleParagraphs,
  sitePermissionPattern,
  permissionPatternMatchesPage,
  sourceIdentityKey,
  sourceContinuityKey,
  sameSourceIdentity,
  hasFreshPreflight,
  handoffId,
  integrityEvidence,
  learningRange,
  updateLearningRangeMode,
  collectContext,
  runPreflight,
  sendToClient,
  openClient,
  checkClient,
  getState: () => ({ backendUrl, clientConnected, currentContext, displayedIdentity, preflightReport, currentTaskId, currentTaskMode, currentTaskContentMode, selectedProcessingMode, sending, sitePermissionEpoch })
};
