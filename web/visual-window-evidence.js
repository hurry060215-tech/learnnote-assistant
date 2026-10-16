// Pure transcript/window review presentation; no browser or lifecycle effects.
(function installModule(global) {
  "use strict";
  const { fmt, escapeHtml, seekTimeButton, seekTimeValue } = global.LearnNoteTaskFormat;

function segmentOverlapsWindow(segment, window) {
  const start = Number(segment.start || 0);
  const end = Number(segment.end ?? start);
  return start < Number(window.end || 0) && end >= Number(window.start || 0);
}

function transcriptLines(segments) {
  return segments.map(seg => `<div class="line" data-line-time="${seekTimeValue(seg.start)}">${seekTimeButton(seg.start)}<span>${escapeHtml(seg.text)}</span></div>`).join("");
}

function visualStudyCueHtml(window, transcript) {
  const segments = transcript?.segments || [];
  const matched = segments.filter(segment => segmentOverlapsWindow(segment, window)).slice(0, 4);
  if (matched.length) {
    return `<div class="visual-study-cues">
      ${matched.map(segment => `<div>${seekTimeButton(segment.start)}<span>${escapeHtml(segment.text)}</span></div>`).join("")}
    </div>`;
  }
  const excerpt = window.transcript_excerpt || "这个窗口暂无字幕摘录，可切到“字幕”查看完整时间轴。";
  return `<p>${escapeHtml(excerpt)}</p>`;
}

function visualWindowSummaryItems(window, transcript = null) {
  const rawItems = [
    window?.local_summary,
    window?.window_summary,
    window?.slice_summary,
    window?.visual_summary,
    window?.summary,
    window?.learning_summary
  ];
  const arrays = [
    window?.key_points,
    window?.summary_points,
    window?.concepts
  ].filter(Array.isArray);
  const items = [];
  const pushText = value => {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (!text || items.includes(text)) return;
    items.push(text);
  };
  rawItems.forEach(value => {
    const text = String(value || "").trim();
    if (!text) return;
    text.split(/\n+|(?:^|\s)[-•]\s+/).forEach(pushText);
  });
  arrays.flat().forEach(pushText);
  if (items.length) return items.slice(0, 3);

  const matched = (transcript?.segments || [])
    .filter(segment => segmentOverlapsWindow(segment, window))
    .slice(0, 2)
    .map(segment => String(segment.text || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  if (matched.length) {
    return matched.map(text => text.length > 120 ? `${text.slice(0, 120).trim()}...` : text);
  }

  const excerpt = String(window?.transcript_excerpt || "").replace(/\s+/g, " ").trim();
  if (excerpt) return [excerpt.length > 160 ? `${excerpt.slice(0, 160).trim()}...` : excerpt];

  const frameTimes = (window?.frame_timestamps || []).slice(0, 3).map(value => fmt(value)).join(" / ");
  return [frameTimes ? `按 ${frameTimes} 这几帧核对本段画面变化。` : "暂无局部总结；先从截图标题、公式、代码或演示状态提炼本段主题。"];
}

function visualWindowSummaryHtml(window, transcript = null) {
  const items = visualWindowSummaryItems(window, transcript);
  return `<div class="visual-window-summary">
    <span>本段要点</span>
    <ul>${items.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
  </div>`;
}

function visualWindowCueSegments(window, transcript = null, limit = 2) {
  return (transcript?.segments || [])
    .filter(segment => segmentOverlapsWindow(segment, window))
    .slice(0, limit)
    .map(segment => ({
      start: Number(segment.start || 0),
      text: String(segment.text || "").replace(/\s+/g, " ").trim()
    }))
    .filter(item => item.text);
}

function visualStudyChecklistHtml(window, transcript) {
  const hasCue = Boolean(window.transcript_excerpt) || (transcript?.segments || []).some(segment => segmentOverlapsWindow(segment, window));
  const target = hasCue
    ? "核对截图里的板书、PPT 切换、代码/界面状态是否已被字幕覆盖。"
    : "先从截图判断这一段的主题，重点看标题、公式、代码和演示状态。";
  const action = hasCue
    ? "复述这一窗口的结论，再按画面顺序补齐遗漏步骤。"
    : "补一句本段主题，再和前后窗口串成完整时间线。";
  return `<div class="visual-study-checklist">
    <span>学习动作</span>
    <ul>
      <li>${escapeHtml(target)}</li>
      <li>${escapeHtml(action)}</li>
    </ul>
  </div>`;
}

function visualStudyCheckpointHtml(window, transcript) {
  const segments = (transcript?.segments || [])
    .filter(segment => segmentOverlapsWindow(segment, window))
    .slice(0, 3)
    .map(segment => ({ seconds: Number(segment.start || 0), time: fmt(segment.start), text: String(segment.text || "").replace(/\s+/g, " ").trim() }))
    .filter(item => item.text);
  if (!segments.length && window.transcript_excerpt) {
    segments.push({
      seconds: Number(window.start || 0),
      time: fmt(window.start || 0),
      text: String(window.transcript_excerpt || "").replace(/\s+/g, " ").trim()
    });
  }
  const items = segments.length
    ? segments.map(item => `<li>${seekTimeButton(item.seconds, "checkpoint-seek")}<span>${escapeHtml(item.text.length > 96 ? `${item.text.slice(0, 96).trim()}...` : item.text)}；对照画面确认对应的板书、PPT、代码或操作步骤。</span></li>`)
    : [`<li><span>无同步字幕；先描述画面网格中的标题、公式、代码或界面状态，再回看原视频确认上下文。</span></li>`];
  return `<div class="visual-study-checkpoints">
    <span>回看检查点</span>
    <ol>${items.join("")}</ol>
  </div>`;
}

function visualStudyQuestionHtml(window, transcript) {
  const segments = (transcript?.segments || [])
    .filter(segment => segmentOverlapsWindow(segment, window))
    .slice(0, 2)
    .map(segment => ({ seconds: Number(segment.start || 0), time: fmt(segment.start), text: String(segment.text || "").replace(/\s+/g, " ").trim() }))
    .filter(item => item.text);
  if (!segments.length && window.transcript_excerpt) {
    segments.push({
      seconds: Number(window.start || 0),
      time: fmt(window.start || 0),
      text: String(window.transcript_excerpt || "").replace(/\s+/g, " ").trim()
    });
  }
  const items = segments.length
    ? segments.map(item => {
      const text = item.text.length > 72 ? `${item.text.slice(0, 72).trim()}...` : item.text;
      return `<li>${seekTimeButton(item.seconds, "question-seek")}<span>这句“${escapeHtml(text)}”在画面中对应的标题、公式、代码或操作状态是什么？</span></li>`;
    })
    : (() => {
      const frameTimes = (window.frame_timestamps || []).slice(0, 3).map(value => fmt(value)).join(" / ");
      return [
        `<li><span>${escapeHtml(frameTimes ? `这些帧（${frameTimes}）里最能说明本段主题的画面证据是什么？` : "这个窗口里最值得回看的标题、公式、代码、界面状态或演示步骤是什么？")}</span></li>`,
        `<li><span>如果没有字幕，能否用一句话描述这组截图的操作顺序或 PPT 结构？</span></li>`
      ];
    })();
  return `<div class="visual-study-questions">
    <span>自测问题</span>
    <ol>${items.join("")}</ol>
  </div>`;
}

  global.LearnNoteVisualWindowEvidence = Object.freeze({
    segmentOverlapsWindow, transcriptLines, visualStudyCueHtml, visualWindowSummaryItems, visualWindowSummaryHtml, visualWindowCueSegments, visualStudyChecklistHtml, visualStudyCheckpointHtml, visualStudyQuestionHtml
  });
})(globalThis);
