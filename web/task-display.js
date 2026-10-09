// Pure task presentation: no DOM, storage, model or network access.
(function installModule(global) {
  "use strict";
  const { compactIdList, fmt, compactUrl } = global.LearnNoteTaskFormat;

function llmAuditFlags(diag = {}) {
  const flags = [];
  if (diag.vision_failed_batch_count) flags.push(`视觉批次失败 ${diag.vision_failed_batch_count}`);
  if (diag.vision_model_rejected_image) flags.push("模型拒绝图片输入");
  if (diag.llm_event_count) flags.push(`LLM 事件 ${diag.llm_event_count}`);
  const lastFailure = diag.llm_last_failure || {};
  if (lastFailure.stage || lastFailure.code) {
    flags.push(`最后失败 ${lastFailure.stage || "llm"}/${lastFailure.code || "unknown"}`);
  }
  return flags;
}

function summaryDiagnosticText(task) {
  const diag = task?.summary_diagnostics || {};
  if (!Object.keys(diag).length) return "-";
  const visionGridCount = diag.vision_grid_count ?? diag.frame_grid_count ?? 0;
  const sentImages = diag.vision_image_count ?? 0;
  const omittedCount = Number(diag.omitted_frame_grid_count || 0);
  const missingImages = diag.all_sent_grids_had_images === false || diag.all_grids_had_images === false;
  const missingWindowIds = compactIdList(diag.missing_vision_image_window_ids);
  const omittedWindowIds = compactIdList(diag.omitted_vision_window_ids);
  return [
    diag.used_vision_llm ? "已使用视觉 LLM" : diag.used_text_llm ? "已使用文本 LLM" : diag.used_local_template ? "本地模板" : "",
    `模型 ${diag.llm_model || task.summary_source || "-"}`,
    diag.llm_provider ? `Provider ${diag.llm_provider}` : "",
    diag.llm_base_host ? `Base ${diag.llm_base_host}` : "",
    diag.llm_failure_code ? `LLM 失败 ${diag.llm_failure_stage || "unknown"}/${diag.llm_failure_code}` : "",
    diag.llm_failure_reason ? `原因 ${diag.llm_failure_reason}` : "",
    `视觉窗口 ${diag.visual_window_count ?? 0}`,
    `画面网格 ${diag.frame_grid_count ?? 0}`,
    `\u9001\u5165\u89c6\u89c9 ${sentImages}/${visionGridCount}`,
    omittedCount > 0 ? `\u8d85\u9650\u7701\u7565 ${omittedCount}` : "",
    missingWindowIds ? `缺图 ${missingWindowIds}` : "",
    omittedWindowIds ? `省略窗口 ${omittedWindowIds}` : "",
    missingImages ? "\u5b58\u5728\u7f3a\u5931\u56fe\u7247" : "",
    ...llmAuditFlags(diag),
    diag.used_page_text_fallback ? `页面文本 ${diag.page_text_char_count ?? 0} 字` : "",
    diag.used_page_text_fallback ? `浏览器字幕 ${diag.browser_subtitle_count ?? 0} 条` : "",
    diag.used_page_text_fallback ? `合并文本 ${diag.combined_text_char_count ?? 0} 字` : "",
    diag.summary_warning || ""
  ].filter(Boolean).join(" · ");
}

function drmSignalText(signals = []) {
  const parts = [];
  const keySystems = [...new Set(signals.map(item => item.key_system).filter(Boolean))];
  const initTypes = [...new Set(signals.map(item => item.init_data_type).filter(Boolean))];
  if (keySystems.length) parts.push(`key system：${keySystems.slice(0, 3).join(", ")}`);
  if (initTypes.length) parts.push(`init data：${initTypes.slice(0, 3).join(", ")}`);
  return parts.join(" · ");
}

function activeVideoText(active) {
  if (!active?.src) return "-";
  return [
    active.paused ? "暂停" : "播放中",
    `${fmt(active.current_time || 0)} / ${fmt(active.duration || 0)}`,
    `${active.width || 0}x${active.height || 0}`,
    active.frame_id !== null && active.frame_id !== undefined ? `frame ${active.frame_id}` : "",
    active.drm_detected ? "DRM/EME" : "",
    active.src
  ].filter(Boolean).join(" · ");
}

function sourceText(task) {
  if (task.mode === "subtitle_only") return "字幕速记";
  if (task.mode === "download_only") return "当前页下载";
  if (task.mode === "rerun_from_media") return "复用本地视频";
  if (task.source_type === "local") return "本地视频";
  if (task.source_type === "page_text") return "页面文本";
  return task.selected_resource ? `直取 · ${mediaKindText(task.selected_resource.kind) || "媒体"}` : "页面解析";
}

function mediaKindText(kind = "") {
  return ({
    hls: "HLS",
    dash: "DASH",
    video: "视频",
    audio: "音频",
    subtitle: "字幕",
    fragment: "分片",
    blob: "Blob"
  })[String(kind || "").toLowerCase()] || kind || "";
}

function playerLibrarySourceText(resource) {
  if (resource?.source !== "pageHookPlayer") return "";
  const label = String(resource.label || "");
  const libraries = [
    [/hls\.js/i, "hls.js"],
    [/dash\.js/i, "dash.js"],
    [/shaka/i, "shaka"],
    [/video\.js/i, "video.js"],
    [/DPlayer/i, "DPlayer"],
    [/ArtPlayer/i, "ArtPlayer"],
    [/\bxgplayer\b|XGPlayer/i, "xgplayer"],
    [/Aliplayer/i, "Aliplayer"],
    [/TcPlayer/i, "TcPlayer"],
    [/jwplayer/i, "jwplayer"]
  ];
  const match = libraries.find(([pattern]) => pattern.test(label));
  if (match) return `${match[1]} 已加载`;
  return "播放器已加载";
}

function resourceSourceText(resource) {
  const playerSource = playerLibrarySourceText(resource);
  if (playerSource) return `${playerSource}源地址`;
  if (resource?.source === "manifest-guess") return "同目录 manifest 猜测";
  if (resource?.source === "inferred-manifest") return "分片路径回推 manifest";
  if (resource?.source === "webRequestResolved") return "最终媒体地址";
  if (resource?.source === "webRequest") return "浏览器请求";
  if (resource?.source === "iframeHint") return "iframe 内播放器线索";
  if (resource?.source === "scriptHint") return "页面脚本线索";
  if (resource?.source === "domHint") return "页面元素线索";
  if (resource?.source === "locationHint") return "页面 URL 线索";
  if (String(resource?.source || "").startsWith("pageHook")) return "页面接口";
  return resource?.source || "";
}

function taskResolvedTargetText(task, limit = 92) {
  const selected = task?.selected_resource || {};
  const target = selected.resolved_url || "";
  if (!target || target === selected.url) return "";
  return compactUrl(target, limit);
}

function playbackText(match) {
  return ({
    "exact-src": "当前 src",
    "source-element": "当前 source",
    "same-frame": "同播放器 frame",
    "blob-same-frame": "blob 播放同 frame",
    "blob-source": "Blob/MSE 来源映射",
    "range-near-playhead": "播放进度附近 Range 请求",
    "manifest-near-playhead": "播放进度附近 Manifest 请求",
    "resolved-final-url": "跳转后的真实媒体",
    "recent-media-request": "最近播放请求",
    "same-site-request": "同站请求",
    "inferred-from-fragment": "分片推断"
  })[match] || match || "";
}

function transcriberLabel(value) {
  return ({
    "faster-whisper": "本地 faster-whisper",
    "openai-compatible": "OpenAI-compatible ASR",
    "openai-compatible-asr": "OpenAI-compatible ASR",
    openai: "OpenAI ASR",
    groq: "Groq ASR",
    "groq-asr": "Groq ASR"
  })[String(value || "faster-whisper").toLowerCase()] || String(value || "ASR");
}

function asrOptionText(options = {}) {
  return `${transcriberLabel(options.transcriber)} · ${options.whisper_model || "small"}`;
}

function transcriptSourceText(source) {
  return ({
    "browser-subtitle": "浏览器字幕",
    "page-subtitle": "页面字幕",
    "embedded-subtitle": "视频内嵌字幕",
    "faster-whisper": "本地 faster-whisper",
    "openai-compatible-asr": "OpenAI-compatible ASR",
    "groq-asr": "Groq ASR"
  })[String(source || "").toLowerCase()] || source || "转写";
}

function optionText(task) {
  const options = task.options || {};
  return [
    options.frame_interval ? `${options.frame_interval} 秒切片` : "",
    options.grid_columns && options.grid_rows ? `${options.grid_columns}x${options.grid_rows} 画面网格` : "",
    asrOptionText(options),
    options.note_style ? `风格 ${options.note_style}` : "",
    options.note_template ? `格式 ${options.note_template}` : "",
    options.visual_understanding === false ? "未开启视觉理解" : "视觉理解"
  ].filter(Boolean).join(" · ");
}


  global.LearnNoteTaskDisplay = Object.freeze({
    llmAuditFlags,
    summaryDiagnosticText,
    drmSignalText,
    activeVideoText,
    sourceText,
    mediaKindText,
    playerLibrarySourceText,
    resourceSourceText,
    taskResolvedTargetText,
    playbackText,
    transcriberLabel,
    asrOptionText,
    transcriptSourceText,
    optionText,
  });
})(globalThis);
