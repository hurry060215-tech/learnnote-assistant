// Stateless classic visual-study rendering; URL/export policy stays with the caller.
(function installModule(global) {
  "use strict";
  const { escapeHtml, fmt, seekTimeValue, seekTimeButton, frameTimestampText } = global.LearnNoteTaskFormat;
  const { visualWindows, displayTaskTitle, hasExportableMedia } = global.LearnNoteTaskList;
  const {
    segmentOverlapsWindow, visualWindowCueSegments, visualWindowSummaryItems,
    visualWindowSummaryHtml, visualStudyCueHtml, visualStudyCheckpointHtml,
    visualStudyQuestionHtml, visualStudyChecklistHtml
  } = global.LearnNoteVisualWindowEvidence;

  function createVisualStudyRenderer({ safeNoteMediaUrl, hasTaskDiagnostics, taskExportUrl, taskClipExportUrl }) {
function visualWindowEvidenceState(task, window, index = 0) {
  const diag = task?.summary_diagnostics || {};
  const id = String(window?.id || `W${String(index + 1).padStart(3, "0")}`);
  const sentIds = new Set((diag.vision_image_window_ids || []).map(value => String(value)));
  const missingIds = new Set((diag.missing_vision_image_window_ids || []).map(value => String(value)));
  const omittedIds = new Set((diag.omitted_vision_window_ids || []).map(value => String(value)));
  if (missingIds.has(id)) {
    return { state: "missing", label: "缺图", detail: "未送入视觉模型，按字幕与索引复习" };
  }
  if (omittedIds.has(id)) {
    return { state: "omitted", label: "已省略", detail: "超出视觉批次上限，保留本地索引" };
  }
  if (sentIds.has(id) || diag.used_vision_llm || task?.summary_source === "vision-llm") {
    return { state: "vision", label: "已进视觉", detail: "网格图已参与图文总结" };
  }
  return { state: "ready", label: "本地索引", detail: safeNoteMediaUrl(window?.grid_url || "") ? "可核对画面和字幕" : "等待网格图" };
}

function visualStudyCorrelationHtml(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const shown = windows.slice(0, 10);
  const rows = shown.map((window, index) => {
    const id = String(window.id || `W${String(index + 1).padStart(3, "0")}`);
    const evidence = visualWindowEvidenceState(task, window, index);
    const image = safeNoteMediaUrl(window.grid_url || "");
    const cues = visualWindowCueSegments(window, transcript, 3);
    const points = visualWindowSummaryItems(window, transcript).slice(0, 2);
    const hasReviewEvidence = Boolean(cues.length || window.transcript_excerpt || (window.frame_timestamps || []).length);
    const cueText = cues.length
      ? `${cues.length} 段字幕 · ${fmt(cues[0].start)} 起`
      : window.transcript_excerpt
        ? "有窗口摘录"
        : "待补字幕";
    const cuePreview = cues[0]?.text || window.transcript_excerpt || "切到字幕页核对完整上下文";
    const summaryText = points[0] || "等待局部总结";
    const secondarySummary = points[1] || evidence.detail;
    return `<article class="${escapeHtml(evidence.state)}" data-visual-window="${escapeHtml(id)}" data-window-start="${seekTimeValue(window.start)}">
      <div class="visual-study-correlation-id">
        <b>${escapeHtml(id)}</b>
        <time>${fmt(window.start)} - ${fmt(window.end)}</time>
      </div>
      <div>
        <span>画面</span>
        <strong>${image ? "截图网格" : "无图"}</strong>
        <small>${escapeHtml(evidence.label)} · ${Number(window.frame_count || 0)} 帧</small>
      </div>
      <div>
        <span>字幕</span>
        <strong>${escapeHtml(cueText)}</strong>
        <small>${escapeHtml(cuePreview.length > 86 ? `${cuePreview.slice(0, 86).trim()}...` : cuePreview)}</small>
      </div>
      <div>
        <span>局部总结</span>
        <strong>${escapeHtml(summaryText.length > 74 ? `${summaryText.slice(0, 74).trim()}...` : summaryText)}</strong>
        <small>${escapeHtml(secondarySummary.length > 96 ? `${secondarySummary.slice(0, 96).trim()}...` : secondarySummary)}</small>
      </div>
      <div>
        <span>复习动作</span>
        <strong>${hasReviewEvidence ? "可自测" : "先看片"}</strong>
        <small>${hasReviewEvidence ? "按画面解释字幕中的标题、公式、代码或操作状态" : "先描述截图再补字幕"}</small>
      </div>
      <nav>
        <button type="button" data-media-seek-time="${seekTimeValue(window.start)}">回看</button>
        <button type="button" data-switch-result-tab="transcript" data-focus-visual-window="${escapeHtml(id)}">字幕</button>
        <button type="button" data-switch-result-tab="note">笔记</button>
      </nav>
    </article>`;
  });
  const remaining = Math.max(0, windows.length - shown.length);
  return `<section class="visual-study-correlation" aria-label="切片证据核对矩阵">
    <header>
      <div>
        <span>证据核对矩阵</span>
        <strong>逐窗对齐画面、字幕、局部总结和复习动作</strong>
      </div>
      <small>${shown.length}/${windows.length} 窗口${remaining ? ` · 余 ${remaining}` : ""}</small>
    </header>
    <div>${rows.join("")}</div>
  </section>`;
}

function visualStudyOverviewHtml(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const firstWindow = windows[0];
  const lastWindow = windows[windows.length - 1];
  const range = firstWindow && lastWindow ? `${fmt(firstWindow.start)} - ${fmt(lastWindow.end)}` : "等待切片";
  const states = windows.map((window, index) => visualWindowEvidenceState(task, window, index).state);
  const visionCount = states.filter(state => state === "vision").length;
  const missingCount = states.filter(state => state === "missing").length;
  const omittedCount = states.filter(state => state === "omitted").length;
  const transcriptSegments = transcript?.segments || [];
  const alignedCueCount = transcriptSegments.filter(segment => windows.some(window => segmentOverlapsWindow(segment, window))).length;
  const cueWindowCount = windows.filter(window => (
    window.transcript_excerpt ||
    transcriptSegments.some(segment => segmentOverlapsWindow(segment, window))
  )).length;
  const frameCount = windows.reduce((total, window) => total + Number(window.frame_count || 0), 0);
  const gridText = task.options?.grid_columns && task.options?.grid_rows
    ? `${task.options.grid_columns}x${task.options.grid_rows}`
    : "网格";
  const quality = missingCount || omittedCount
    ? "部分窗口需要人工核对"
    : visionCount
      ? "图文证据完整"
      : "本地索引可复习";
  const cards = [
    { label: "覆盖范围", value: range, detail: `${windows.length} 个视觉窗口` },
    { label: "视觉总结", value: visionCount ? `${visionCount}/${windows.length} 已参与` : "未调用视觉", detail: quality },
    { label: "字幕对齐", value: alignedCueCount ? `${alignedCueCount} 段` : "无匹配字幕", detail: cueWindowCount ? `${cueWindowCount}/${windows.length} 窗口有线索` : transcriptSegments.length ? "可逐窗核对" : "等待转写产物" },
    { label: "画面证据", value: `${frameCount} 帧`, detail: `${gridText} 截图网格` }
  ];
  return `<section class="visual-study-overview" aria-label="切片学习总览">
    <header>
      <div>
        <span>切片总览</span>
        <strong>${escapeHtml(quality)}</strong>
      </div>
      <small>${escapeHtml(displayTaskTitle(task, "视觉窗口"))}</small>
    </header>
    <div class="visual-study-overview-grid">
      ${cards.map(card => `<article>
        <span>${escapeHtml(card.label)}</span>
        <strong>${escapeHtml(card.value)}</strong>
        <small>${escapeHtml(card.detail)}</small>
      </article>`).join("")}
    </div>
    ${(missingCount || omittedCount) ? `<p>有 ${missingCount + omittedCount} 个窗口未完整进入视觉模型；请优先打开对应卡片，结合截图和字幕人工核对。</p>` : ""}
    <nav>
      <button type="button" data-switch-result-tab="transcript">核对字幕</button>
      <button type="button" data-switch-result-tab="note">回到笔记</button>
      ${hasTaskDiagnostics(task) ? `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>` : ""}
      <a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">导出切片索引</a>
    </nav>
  </section>`;
}

function visualWindowReviewItem(task, window, index = 0, transcript = null) {
  const id = String(window?.id || `W${String(index + 1).padStart(3, "0")}`);
  const evidence = visualWindowEvidenceState(task, window, index);
  const cues = visualWindowCueSegments(window, transcript, 3);
  const hasImage = Boolean(safeNoteMediaUrl(window?.grid_url || ""));
  const points = visualWindowSummaryItems(window, transcript).filter(Boolean);
  const hasSummary = points.some(point => point && !/暂无局部总结|先从截图/i.test(point));
  const frameCount = Number(window?.frame_count || 0);
  let priority = 5;
  let label = "常规复核";
  let reason = "确认画面、字幕和笔记结论一致。";
  if (evidence.state === "missing" || evidence.state === "omitted") {
    priority = 0;
    label = "优先核对";
    reason = evidence.detail;
  } else if (!hasImage) {
    priority = 1;
    label = "缺少截图";
    reason = "没有截图网格，先用字幕和前后窗口补全上下文。";
  } else if (!cues.length && !window?.transcript_excerpt) {
    priority = 2;
    label = "补字幕线索";
    reason = "没有同步字幕，先看截图判断本段主题。";
  } else if (!hasSummary) {
    priority = 3;
    label = "补局部总结";
    reason = "已有画面或字幕，但本段总结仍需要人工提炼。";
  } else if (evidence.state === "vision") {
    priority = 4;
    label = "快速确认";
    reason = "已进入视觉模型，复核重点是模型是否漏掉画面细节。";
  }
  return {
    id,
    window,
    evidence,
    priority,
    label,
    reason,
    cueCount: cues.length || (window?.transcript_excerpt ? 1 : 0),
    frameCount,
    hasSummary,
    summary: points[0] || reason
  };
}

function visualStudyReviewPathHtml(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const items = windows
    .map((window, index) => visualWindowReviewItem(task, window, index, transcript))
    .sort((left, right) => left.priority - right.priority || Number(left.window.start || 0) - Number(right.window.start || 0));
  const shown = items.slice(0, 6);
  const urgentCount = items.filter(item => item.priority <= 2).length;
  const readyCount = items.filter(item => item.evidence.state === "vision" || item.hasSummary).length;
  return `<section class="visual-review-path" aria-label="切片复核路线">
    <header>
      <div>
        <span>复核路线</span>
        <strong>${urgentCount ? `先处理 ${urgentCount} 个重点窗口` : "按时间线快速复核"}</strong>
      </div>
      <small>${readyCount}/${items.length} 窗口已有总结或视觉证据</small>
    </header>
    <div class="visual-review-path-list">
      ${shown.map(item => `<article class="${escapeHtml(item.evidence.state)} priority-${item.priority}">
        <button type="button" class="visual-review-path-main" data-switch-result-tab="slices" data-focus-visual-window="${escapeHtml(item.id)}">
          <b>${escapeHtml(item.id)}</b>
          <span>${escapeHtml(item.label)}</span>
          <strong>${fmt(item.window.start)} - ${fmt(item.window.end)}</strong>
          <small>${escapeHtml(item.reason)}</small>
        </button>
        <div>
          <em>${item.frameCount || "-"} 帧</em>
          <em>${item.cueCount || "-"} 字幕</em>
          <em>${escapeHtml(item.hasSummary ? "有总结" : "待总结")}</em>
        </div>
        <p>${escapeHtml(String(item.summary || item.reason).replace(/\s+/g, " ").slice(0, 160))}</p>
        <nav>
          <button type="button" data-media-seek-time="${seekTimeValue(item.window.start)}">回看</button>
          <button type="button" data-switch-result-tab="transcript" data-focus-visual-window="${escapeHtml(item.id)}">字幕</button>
        </nav>
      </article>`).join("")}
    </div>
    ${items.length > shown.length ? `<footer>还有 ${items.length - shown.length} 个窗口；导出切片索引可查看完整顺序。</footer>` : ""}
  </section>`;
}

function visualStudyHandoutHtml(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const shown = windows.slice(0, 8);
  const remaining = Math.max(0, windows.length - shown.length);
  return `<section class="visual-study-handout" aria-label="切片讲义时间轴">
    <header>
      <div>
        <span>切片讲义时间轴</span>
        <strong>${escapeHtml(displayTaskTitle(task, "切片讲义"))}</strong>
      </div>
      <small>画面-字幕-总结对齐</small>
    </header>
    <div class="visual-study-handout-list">
      ${shown.map((window, index) => {
        const id = String(window.id || `W${String(index + 1).padStart(3, "0")}`);
        const image = safeNoteMediaUrl(window.grid_url || "");
        const evidence = visualWindowEvidenceState(task, window, index);
        const points = visualWindowSummaryItems(window, transcript).slice(0, 2);
        const cues = visualWindowCueSegments(window, transcript, 2);
        const cueHtml = cues.length
          ? cues.map(cue => `<p>${seekTimeButton(cue.start, "window-seek")}<span>${escapeHtml(cue.text.length > 130 ? `${cue.text.slice(0, 130).trim()}...` : cue.text)}</span></p>`).join("")
          : `<p><span>${escapeHtml(String(window.transcript_excerpt || "暂无字幕线索；先看截图中的标题、公式、代码或演示状态。").replace(/\s+/g, " ").trim())}</span></p>`;
        return `<article class="${escapeHtml(evidence.state)}" data-visual-window="${escapeHtml(id)}" data-window-start="${seekTimeValue(window.start)}">
          <div class="visual-study-handout-time">
            <b>${escapeHtml(id)}</b>
            <time>${fmt(window.start)} - ${fmt(window.end)}</time>
            <em>${escapeHtml(evidence.label)}</em>
          </div>
          <div class="visual-study-handout-body">
            <div class="visual-study-handout-title">
              <strong>${escapeHtml(points[0] || "先核对本段画面变化")}</strong>
              <small>${escapeHtml(evidence.detail)} · ${Number(window.frame_count || 0)} 帧</small>
            </div>
            ${image ? `<figure><img src="${image}" alt="${escapeHtml(id)} frame grid"><figcaption>${escapeHtml(frameTimestampText(window) || "截图网格")}</figcaption></figure>` : ""}
            ${points.length > 1 ? `<ul>${points.slice(1).map(point => `<li>${escapeHtml(point)}</li>`).join("")}</ul>` : ""}
            <div class="visual-study-handout-cues">${cueHtml}</div>
            <div class="visual-study-handout-actions">
              <button type="button" data-media-seek-time="${seekTimeValue(window.start)}">回看</button>
              <button type="button" data-switch-result-tab="transcript" data-focus-visual-window="${escapeHtml(id)}">字幕</button>
              ${image ? `<a href="${escapeHtml(image)}" target="_blank" rel="noreferrer">网格</a>` : ""}
            </div>
          </div>
        </article>`;
      }).join("")}
    </div>
    ${remaining ? `<footer>还有 ${remaining} 个窗口；导出切片索引可查看完整列表。</footer>` : ""}
  </section>`;
}

function visualStudyDeck(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const firstWindow = windows[0];
  const lastWindow = windows[windows.length - 1];
  const range = firstWindow && lastWindow ? `${fmt(firstWindow.start)} - ${fmt(lastWindow.end)}` : "等待切片";
  const matchedCueCount = (transcript?.segments || []).filter(segment => windows.some(window => segmentOverlapsWindow(segment, window))).length;
  const headDetail = matchedCueCount ? `${windows.length} 个窗口 · ${matchedCueCount} 段字幕已同步` : `${windows.length} 个窗口 · ${range}`;
  return `<section class="visual-study-deck" aria-label="视觉窗口复习">
    <div class="visual-study-head">
      <div>
        <span>视觉窗口复习</span>
        <strong>${escapeHtml(displayTaskTitle(task, "画面切片"))}</strong>
      </div>
      <div class="visual-study-head-actions">
        <small>${escapeHtml(headDetail)}</small>
        <a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">导出切片索引</a>
      </div>
    </div>
    <div class="visual-study-list">
      ${windows.map((window, index) => {
        const image = safeNoteMediaUrl(window.grid_url || "");
        const evidence = visualWindowEvidenceState(task, window, index);
        return `<article class="visual-study-card ${escapeHtml(evidence.state)}" data-visual-window="${escapeHtml(window.id || "")}" data-window-start="${seekTimeValue(window.start)}">
          <figure>
            ${image ? `<img src="${image}" alt="${escapeHtml(window.id)} frame grid">` : `<div class="visual-study-placeholder">无画面</div>`}
            <figcaption>${escapeHtml(window.id || `W${String(index + 1).padStart(3, "0")}`)}</figcaption>
          </figure>
          <div class="visual-study-card-body">
            <span>窗口 ${String(index + 1).padStart(2, "0")}</span>
            <strong>${fmt(window.start)} - ${fmt(window.end)}</strong>
            <small class="visual-study-evidence ${escapeHtml(evidence.state)}">${escapeHtml(evidence.label)} · ${escapeHtml(evidence.detail)}</small>
            ${visualWindowSummaryHtml(window, transcript)}
            ${visualStudyCueHtml(window, transcript)}
            ${visualStudyCheckpointHtml(window, transcript)}
            ${visualStudyQuestionHtml(window, transcript)}
            ${visualStudyChecklistHtml(window, transcript)}
            ${hasExportableMedia(task) ? `<p class="visual-clip-action"><a href="${escapeHtml(taskClipExportUrl(task, window.id || `W${String(index + 1).padStart(3, "0")}`))}">导出片段</a></p>` : ""}
            <div class="visual-study-meta">
              <em>${Number(window.frame_count || 0)} 帧</em>
              ${frameTimestampText(window) ? `<em>${escapeHtml(frameTimestampText(window))}</em>` : ""}
              <em>${escapeHtml(task.options?.grid_columns && task.options?.grid_rows ? `${task.options.grid_columns}x${task.options.grid_rows}` : "网格")}</em>
              <em>${escapeHtml(task.summary_source || "本地索引")}</em>
            </div>
            <div class="visual-study-actions">
              <button type="button" data-media-seek-time="${seekTimeValue(window.start)}">回看此段</button>
              <button type="button" data-switch-result-tab="transcript">看对应字幕</button>
              <button type="button" data-switch-result-tab="note">回到笔记</button>
            </div>
          </div>
        </article>`;
      }).join("")}
    </div>
  </section>`;
}

function visualStudyNavigatorHtml(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const diag = task.summary_diagnostics || {};
  const sentIds = new Set((diag.vision_image_window_ids || []).map(value => String(value)));
  const missingIds = new Set((diag.missing_vision_image_window_ids || []).map(value => String(value)));
  const omittedIds = new Set((diag.omitted_vision_window_ids || []).map(value => String(value)));
  const items = windows.map((window, index) => {
    const id = String(window.id || `W${String(index + 1).padStart(3, "0")}`);
    const matched = (transcript?.segments || []).filter(segment => segmentOverlapsWindow(segment, window));
    let state = "ready";
    if (missingIds.has(id)) state = "missing";
    else if (omittedIds.has(id)) state = "omitted";
    else if (sentIds.has(id) || diag.used_vision_llm || task.summary_source === "vision-llm") state = "vision";
    const label = {
      vision: "已进视觉",
      ready: "本地索引",
      missing: "缺图",
      omitted: "已省略"
    }[state];
    return `<button type="button" class="${escapeHtml(state)}" data-media-seek-time="${seekTimeValue(window.start)}" data-window-start="${seekTimeValue(window.start)}">
      <span>${escapeHtml(id)}</span>
      <strong>${fmt(window.start)} - ${fmt(window.end)}</strong>
      <small>${escapeHtml(label)} · ${Number(window.frame_count || 0)} 帧 · ${matched.length || 0} 字幕</small>
    </button>`;
  });
  return `<section class="visual-study-navigator" aria-label="视觉窗口学习队列">
    <header>
      <span>复习队列</span>
      <strong>按画面窗口回看</strong>
      <small>先扫窗口，再进入下方卡片核对字幕、截图和自测题。</small>
    </header>
    <div>${items.join("")}</div>
  </section>`;
}

    return Object.freeze({
      visualWindowEvidenceState, visualWindowReviewItem, visualStudyCorrelationHtml,
      visualStudyOverviewHtml, visualStudyReviewPathHtml, visualStudyHandoutHtml,
      visualStudyDeck, visualStudyNavigatorHtml
    });
  }
  global.LearnNoteVisualStudy = Object.freeze({ createVisualStudyRenderer });
})(globalThis);
