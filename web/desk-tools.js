import { mountSupportSummary } from "/web/support-summary.js";
import { eventLogHtml, timelineHtml } from "/web/desk-progress.js";
import { fullVideoSource } from "/web/range-source.js";
import { canRedecodeMaterial, installMaterialEncoding } from "/web/desk-material-encoding.js";
import {
  api as request,
  escapeHtml as esc,
  timestamp,
  taskAsset,
} from "/web/desk-api.js";

export function installTools(ctx) {
  const { state, options, openItem, refresh, notice, guard } = ctx;
  const $ = (id) => document.getElementById(id);
  const dialog = document.createElement("dialog");
  dialog.id = "toolsDialog";
  dialog.className = "tools-dialog";
  document.body.append(dialog);
  let generation = 0,
    course = null,
    courses = [],
    courseEpisodes = [],
    proposals = [],
    batchRunning = false,
    cleanupPolicy = null,
    backAction = null;
  async function api(path, options) {
    const token = generation;
    const result = await request(path, options);
    if (token !== generation)
      throw new Error("已离开此操作页面；已提交的操作可在重新打开后查看。");
    return result;
  }
  function show(title, body) {
    generation++;
    backAction = state.selected ? more : null;
    dialog.innerHTML = `<header><button data-tool-back type="button" aria-label="返回">← 返回</button><h2>${esc(title)}</h2><button data-close-tool aria-label="关闭">×</button></header><div id="toolBody">${body}</div><p id="toolStatus" role="status"></p>`;
    if (!dialog.open) dialog.showModal();
    return generation;
  }
  function status(text) {
    const el = $("toolStatus");
    if (el) el.textContent = text;
  }
  const materialEncoding = installMaterialEncoding({ state, dialog, show, status, refresh, generation: () => generation });
  async function run(button, work) {
    const token = generation;
    if (button) button.disabled = true;
    try {
      await work(token);
    } catch (error) {
      if (token === generation) status(error.message);
    } finally {
      if (button?.isConnected) button.disabled = false;
    }
  }
  const safeLink = (url) => (/^\/api\//.test(url) ? url : "#");
  function links(items) {
    return items
      .map(
        ([label, url]) =>
          `<a class="tool-link" href="${esc(safeLink(url))}" download>${esc(label)} ↗</a>`,
      )
      .join("");
  }
  function current() {
    if (!state.selected) throw new Error("请先打开一份笔记。");
    return { ...state.selected };
  }
  function selectItems(selected = []) {
    return state.items
      .map(
        (item) =>
          `<label class="tool-choice"><input type="checkbox" data-source="${esc(item.id)}" data-kind="${item.kind}" ${selected.some((s) => s.kind === item.kind && s.id === item.id) ? "checked" : ""}><span>${esc(item.title)}<small>${item.kind === "task" ? "视频笔记" : "学习资料"}</small></span></label>`,
      )
      .join("");
  }
  async function saveCourse(next) {
    const result = await api(`/api/courses${course ? "/" + course.id : ""}`, {
      method: course ? "PUT" : "POST",
      body: JSON.stringify({
        title: next.title,
        sources: next.sources,
        paused: next.paused,
        revision: course?.revision || 0,
      }),
    });
    course = result.course;
    courseEpisodes = result.episodes || [];
    window.LearnNoteDialogs?.markSaved(dialog);
    return course;
  }
  async function listCourses() {
    const token = show("课程", '<p class="muted">正在读取课程…</p>');
    const result = await api("/api/courses");
    if (token !== generation) return;
    courses = result.courses;
    backAction = null;
    $("toolBody").innerHTML =
      `<p class="muted">把相关笔记放在一起，按自己的顺序学习。</p><button class="primary" data-action="new-course">＋ 新建课程</button><div class="tool-list">${courses.map((c) => `<button class="tool-row" data-course="${c.id}"><strong>${esc(c.title)}</strong><small>${c.paused ? "已暂停" : "学习中"}</small><span>›</span></button>`).join("") || '<p class="muted">还没有课程。</p>'}</div>`;
  }
  function courseEditor() {
    show(
      course ? "编辑课程" : "新建课程",
      `<form id="courseForm"><label for="courseTitle">课程名称</label><input id="courseTitle" required maxlength="200" value="${esc(course?.title || "")}"><label>选择已有笔记</label><div class="source-picker">${selectItems(course?.sources || []) || '<p class="muted">还没有笔记，可先添加视频链接。</p>'}</div><label for="courseLinks">视频链接 · 每行一个</label><textarea id="courseLinks" rows="4" placeholder="https://…">${esc(
        (course?.sources || [])
          .filter((s) => s.kind === "url")
          .map((s) => s.url)
          .join("\n"),
      )}</textarea><details><summary>从公开播放列表展开</summary><label for="playlistUrl">播放列表地址</label><input id="playlistUrl" type="url"><button type="button" data-action="playlist">预览链接</button><div id="playlistResult"></div></details><footer><button class="primary">保存课程</button></footer></form>`,
    );
    backAction = course ? courseView : listCourses;
  }
  async function openCourse(id) {
    const token = show("课程", '<p class="muted">正在读取…</p>');
    const result = await api(`/api/courses/${id}`);
    if (token !== generation) return;
    course = result.course;
    courseEpisodes = result.episodes || [];
    courseView();
  }
  function episodeLabel(source, position) {
    const episode = courseEpisodes.find(item => item.position === position);
    if (!episode) return source.kind === "url" ? "待整理链接" : source.kind === "task" ? "视频笔记" : "学习资料";
    const label = { pending:"待提交", queued:"排队中", running:"处理中", success:"已完成", failed:"处理失败", cancelled:"已取消", interrupted:"等待恢复", source_missing:"任务已移除，可重新提交", identity_conflict:"来源冲突，请核对" }[episode.status] || episode.status;
    return `${label}${episode.checkpoint ? ` · ${episode.checkpoint}` : ""}${episode.resource_budget_mb ? ` · 预算 ${episode.resource_budget_mb} MB` : ""}`;
  }
  function courseView() {
    show(
      course.title,
      `<div class="tool-actions"><button data-action="courses">所有课程</button><button data-action="refresh-course">刷新分集状态</button><button data-action="edit-course">编辑来源</button><button data-action="pause-course">${course.paused ? "继续课程" : "暂停课程"}</button><button data-action="batch" ${course.paused ? "disabled" : ""}>整理待处理链接</button></div><div class="tool-list">${course.sources.map((s, i) => `<div class="tool-row"><button class="grow" data-open-source="${i}"><strong>${esc(s.title || s.url || s.id)}</strong><small>${esc(episodeLabel(s, i))}</small></button>${courseEpisodes.find(item => item.position === i)?.retryable ? `<button data-retry-episode="${esc(courseEpisodes.find(item => item.position === i).episode_id)}" ${course.paused ? "disabled" : ""}>恢复此集</button>` : ""}<button data-move="${i}" data-direction="-1" aria-label="上移" ${i === 0 ? "disabled" : ""}>↑</button><button data-move="${i}" data-direction="1" aria-label="下移" ${i === course.sources.length - 1 ? "disabled" : ""}>↓</button></div>`).join("")}</div><details><summary>对照不同来源</summary><form id="compareForm"><label for="compareQuery">查找共同讨论的内容</label><input id="compareQuery" required placeholder="输入关键词"><label for="compareSourceKind">来源类型</label><select id="compareSourceKind"><option value="">全部来源</option><option value="task">视频</option><option value="material">文档</option></select><label for="compareSourceId">具体来源</label><select id="compareSourceId"><option value="">全部来源</option>${course.sources.filter(item => item.kind !== "url").map(item => `<option value="${esc(item.id)}">${esc(item.title || item.id)}</option>`).join("")}</select><label for="compareStart">起点（秒，可留空）</label><input id="compareStart" type="number" min="0" step="0.1"><label for="compareEnd">终点（秒，可留空）</label><input id="compareEnd" type="number" min="0" step="0.1"><button>查找出处</button></form><div id="compareResults"></div></details><footer><button data-action="course-review">复习这门课程</button><button class="danger" data-action="delete-course">删除课程分组</button></footer>`,
    );
    backAction = listCourses;
  }
  async function studySettings(courseId = "", taskId = "") {
    const token = show("复习与计划", '<p class="muted">正在读取…</p>');
    await api("/api/study/plan/initialize", {
      method: "POST",
      body: JSON.stringify({
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }),
    });
    const [plan, history, dashboard] = await Promise.all([
      api("/api/study/plan"),
      api("/api/study/reviews?limit=20"),
      api("/api/study/dashboard?limit=12&course_id=" + encodeURIComponent(courseId) + "&task_id=" + encodeURIComponent(taskId)),
    ]);
    if (token !== generation) return;
    const p = plan.plan;
    $("toolBody").innerHTML =
      `<div class="study-overview"><p><span>当前到期</span><strong>${dashboard.today?.due_count ?? 0}</strong></p><p><span>今日已复习</span><strong>${dashboard.today?.reviewed_count ?? 0}</strong></p><p><span>每日目标</span><strong>${p.daily_target}</strong></p></div><div class="tool-actions"><button class="primary" data-action="${p.paused ? "resume-study" : "start-review"}" data-course-id="${esc(courseId)}" data-task-id="${esc(taskId)}">${p.paused ? "继续计划" : "开始复习"}</button></div><details class="study-plan"><summary>调整每日目标与时区</summary><form id="planForm"><label for="dailyTarget">每日目标</label><input id="dailyTarget" type="number" min="1" max="200" value="${p.daily_target}"><label for="studyTimezone">复习时区</label><input id="studyTimezone" value="${esc(p.timezone)}" required><label class="check"><input id="studyPaused" type="checkbox" ${p.paused ? "checked" : ""}>暂停学习记录、提醒与评分</label><button class="primary">保存计划</button></form></details><div class="tool-actions">${links([["导出学习记录", "/api/study/export"]])}</div><details><summary>最近评分记录</summary><div>${history.reviews.map((r) => `<p class="record">${esc(r.reviewed_at || r.created_at || "")} · 评分 ${esc(r.rating)}</p>`).join("") || '<p class="muted">还没有评分记录。</p>'}</div></details><details><summary>修复旧版复习调度</summary><p class="muted">根据完整评分历史重新计算计划，并在本地保存原调度备份。</p><button data-action="rebuild-study">按历史重建</button></details>`;
    const videoLabel=document.createElement("label");videoLabel.htmlFor="studyVideoFilter";videoLabel.textContent="视频范围";
    const videoFilter=document.createElement("select");videoFilter.id="studyVideoFilter";
    videoFilter.append(Object.assign(document.createElement("option"),{value:"",textContent:"全部视频与资料"}));
    for(const source of state.items.filter(item=>item.kind === "task"))videoFilter.append(Object.assign(document.createElement("option"),{value:source.id,textContent:source.title}));
    videoFilter.value=taskId;videoFilter.onchange=()=>studySettings(courseId,videoFilter.value).catch(error=>status(error.message));
    const scopeHint=document.createElement("p");scopeHint.className="muted";scopeHint.textContent="到期和题目使用所选范围；每日目标与活动统计仍覆盖全部本地资料。";
    $("toolBody").append(videoLabel,videoFilter,scopeHint);
    const recentActivity = (dashboard.progress?.activity || []).reduce((sum, day) => ({
      reading: sum.reading + Number(day.reading_count || 0),
      answer: sum.answer + Number(day.answer_count || 0),
      selfAssessment: sum.selfAssessment + Number(day.self_assessment_count || 0),
      review: sum.review + Number(day.review_count || 0),
    }), { reading: 0, answer: 0, selfAssessment: 0, review: 0 });
    const progress = document.createElement("section"); progress.className = "study-progress-summary";
    const progressTitle = document.createElement("h3"); progressTitle.textContent = "近 14 天的本地学习活动";
    const activityText = document.createElement("p"); activityText.textContent = `阅读 ${recentActivity.reading} 次 · 作答 ${recentActivity.answer} 次 · 自我解释 ${recentActivity.selfAssessment} 次 · 复习 ${recentActivity.review} 张`;
    const mastery = dashboard.progress?.mastery || {};
    const masteryText = document.createElement("p"); masteryText.textContent = `全部资料卡片：新卡 ${Number(mastery.new || 0)} · 学习中 ${Number(mastery.learning || 0)} · 需重温 ${Number(mastery.needs_attention || 0)} · 已稳定 ${Number(mastery.retained || 0)}`;
    const heatmap = document.createElement("ol"); heatmap.className = "study-activity-grid";
    heatmap.setAttribute("aria-label", "近 14 天本地复习记录，按计划时区统计");
    for (const day of dashboard.progress?.activity || []) {
      const cell = document.createElement("li"), count = Number(day.review_count || 0);
      cell.dataset.level = String(Math.min(3, count));
      cell.setAttribute("aria-label", `${day.date} · 复习 ${count} 张`);
      const date = document.createElement("small"); date.textContent = String(day.date).slice(5);
      const value = document.createElement("strong"); value.textContent = String(count);
      cell.append(date, value); heatmap.append(cell);
    }
    progress.append(progressTitle, activityText, masteryText, heatmap); $("toolBody").append(progress);
    const backupPanel = document.createElement("details");
    backupPanel.className = "study-backup";
    const backupSummary = document.createElement("summary"); backupSummary.textContent = "备份与恢复";
    const backupHint = document.createElement("p"); backupHint.className = "muted";
    backupHint.textContent = "包含评分历史、计划、个人批注和笔记修改。恢复只合并缺失内容，不覆盖本机现有记录；原始资料需要先恢复到本机。";
    const backupActions = document.createElement("div"); backupActions.className = "tool-actions";
    const exportBackup = document.createElement("a"); exportBackup.textContent = "导出学习备份"; exportBackup.href = "/api/study/backup"; exportBackup.download = `learnnote-learning-backup-${new Date().toISOString().slice(0, 10)}.json`;
    const restoreButton = document.createElement("button"); restoreButton.type = "button"; restoreButton.textContent = "选择备份并恢复";
    const backupFile = document.createElement("input"); backupFile.type = "file"; backupFile.accept = "application/json,.json"; backupFile.hidden = true; backupFile.setAttribute("aria-label", "选择 LearnNote 学习备份");
    restoreButton.onclick = () => backupFile.click();
    backupFile.onchange = async () => {
      const file = backupFile.files?.[0];
      if (!file) return;
      if (file.size > 100_000_000) { status("学习备份超过 100 MB，未写入任何数据。"); backupFile.value = ""; return; }
      if (!confirm("将评分、计划、个人批注和笔记修改合并到本机；现有条目不会被覆盖。原始资料需要先恢复，继续吗？")) { backupFile.value = ""; return; }
      try {
        const payload = JSON.parse(await file.text());
        const result = await api("/api/study/backup/restore", { method: "POST", body: JSON.stringify(payload) });
        const merge = result.merge || {};
        status(`已恢复 ${merge.restored_reviews || 0} 条评分、${merge.restored_annotations || 0} 条批注和 ${merge.restored_editions || 0} 份修改。`);
        await studySettings(courseId,taskId);
      } catch (error) { status(error.message || "备份无效或无法恢复。"); }
      finally { backupFile.value = ""; }
    };
    backupActions.append(exportBackup, restoreButton, backupFile);
    backupPanel.append(backupSummary, backupHint, backupActions);
    const deleteStudy = document.createElement("button"); deleteStudy.type = "button"; deleteStudy.className = "danger";
    deleteStudy.textContent = "永久删除学习记录";
    deleteStudy.onclick = async () => {
      if (!confirm("永久删除全部卡片、评分、自评动作、计划和调度备份？原始资料、正文及个人批注保留。此操作不能撤销。")) return;
      deleteStudy.disabled = true;
      try { await api("/api/study/data?confirm=delete_all_study_data", { method: "DELETE" }); await studySettings(courseId,taskId); }
      catch (error) { status(error.message); deleteStudy.disabled = false; }
    };
    backupPanel.append(deleteStudy);
    $("toolBody").append(backupPanel);
    if (dashboard?.mistakes?.length) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "错题回看 · " + dashboard.mistakes.length + " 条";
      details.append(summary);
      for (const mistake of dashboard.mistakes) {
        const item = document.createElement("article");
        item.className = "record";
        item.textContent = mistake.question + " · 上次评分 " + mistake.reviewed_at;
        const answer = document.createElement("details");
        const answerSummary = document.createElement("summary");
        answerSummary.textContent = "显示答案与复习提示";
        const answerText = document.createElement("p");
        answerText.textContent = mistake.answer || "没有保存答案，请重新生成这张卡片。";
        answer.append(answerSummary, answerText);
        item.append(answer);
        if (mistake.source_evidence_ids?.length) {
          const source = document.createElement("button");
          source.type = "button";
          source.textContent = "查看依据";
          source.onclick = async () => {
            dialog.close();
            try { await ctx.openEvidence(mistake.source_evidence_ids[0]); }
            catch (error) { notice(error.message || "引用出处暂不可用。"); }
          };
          item.append(source);
        }
        details.append(item);
      }
      $("toolBody").append(details);
    }
    backAction = courseId
      ? () => openCourse(courseId)
      : () => {
          dialog.close();
          $("settings").click();
          document.querySelector('[data-settings-section="storage"]')?.click();
        };
  }
  async function propose() {
    const s = current(),
      token = show(
        "从当前内容创建复习卡",
        '<p class="muted">正在读取来源证据…</p>',
      );
    let result;
    if (s.kind === "task")
      result = await api(`/api/tasks/${s.id}/study-proposals`, {
        method: "POST",
      });
    else {
      const data = await api(`/api/library/materials/${s.id}/anchors`);
      result = await api("/api/study/proposals", {
        method: "POST",
        body: JSON.stringify({
          evidence_ids: data.anchors.map((a) => a.evidence_id).slice(0, 100),
          limit: 12,
        }),
      });
    }
    if (token !== generation) return;
    proposals = result.proposals || [];
    $("toolBody").innerHTML =
      `<p class="muted">先检查问题、答案和原始出处，再加入复习。</p><form id="cardsForm">${proposals.map((c, i) => `<section class="proposal"><label class="check"><input type="checkbox" data-card-index="${i}" checked>加入这张卡片</label><label for="front${i}">问题</label><input id="front${i}" maxlength="1000" value="${esc(c.front)}"><label for="back${i}">答案</label><textarea id="back${i}" maxlength="4000">${esc(c.back)}</textarea><button type="button" data-evidence="${esc(c.source_evidence_ids[0] || "")}">查看原始出处</button></section>`).join("") || "<p>没有可用的来源证据，请先完成内容处理。</p>"}<footer><button class="primary" ${proposals.length ? "" : "disabled"}>加入复习库</button></footer></form>`;
  }
  function range() {
    const s = current();
    if (s.kind !== "task") throw new Error("片段学习需要本地视频。");
    show(
      "只整理一段视频",
      `<p class="muted">起止位置以当前视频的秒数计算。新片段会创建独立笔记。${Object.keys(s.learning_range || {}).length ? ` 当前片段边界：${Number(s.learning_range.original_start ?? s.learning_range.start)}–${Number(s.learning_range.original_end ?? s.learning_range.end)} 秒。` : ""}</p>${Object.keys(s.learning_range || {}).length ? '<button data-action="learn-full-source">整理完整原视频（复用已保存媒体）</button>' : ""}<form id="rangeForm"><label for="rangeStart">开始（秒）</label><input id="rangeStart" type="number" min="0" step="0.1" required value="${Math.floor($("player").currentTime || 0)}"><label for="rangeEnd">结束（秒）</label><input id="rangeEnd" type="number" min="0.1" step="0.1" required><button type="button" data-action="range-position">用当前播放位置填入开始</button><footer><button class="primary">整理此片段</button></footer></form>`,
    );
    dialog.dataset.sourceId = s.id;
  }
  async function ocr() {
    const s = current();
    const token = show(
      "画面文字",
      '<p class="muted">正在读取本地 OCR 结果…</p>',
    );
    const result = await api(`/api/tasks/${s.id}/ocr`);
    if (token !== generation) return;
    $("toolBody").innerHTML =
      `<p class="muted">识别文字可能有错；置信度不代表已经核验。请对照原图。</p>${result.frames?.length ? result.frames.map((f) => `<section class="ocr-frame"><h3>${timestamp(f.timestamp)}</h3>${taskAsset(f.image_url, s.id) ? `<img src="${esc(taskAsset(f.image_url, s.id))}" alt="${timestamp(f.timestamp)} 原始画面" loading="lazy">` : ""}${f.lines.map((l) => `<p>${esc(l.text)} <small>置信度 ${Math.round(l.confidence * 100)}% · 未核验</small></p>`).join("")}</section>`).join("") : '<p>当前笔记还没有 OCR 结果。可开启本地 OCR，使用缓存视频重新整理。</p><button data-action="run-ocr">开启 OCR 并重新整理</button>'}${links([["导出 OCR 数据", `/api/tasks/${s.id}/ocr`]])}`;
    dialog.dataset.sourceId = s.id;
  }
  function exports() {
    const s = current();
    const exportBase = s.kind === "task" ? `/api/tasks/${s.id}/exports` : `/api/library/materials/${s.id}/exports`;
    const token = show("统一导出", `<p class="muted">笔记和学习资料共享同一份结构化正文。预览会使用个人补充、出处、时间点、图片与练习的当前选择。</p><div class="unified-export-grid"><label>格式<select id="unifiedExportFormat"><option value="html">HTML（离线预览）</option><option value="docx">Word</option><option value="pdf">PDF</option></select></label><label>字体<select id="unifiedExportFont"><option>Microsoft YaHei</option><option>Noto Sans SC</option><option>SimSun</option><option>Arial</option></select></label><label>字号<input id="unifiedExportSize" type="number" min="8" max="36" step="0.5" value="10.5"></label><label>行距<input id="unifiedExportLeading" type="number" min="1" max="3" step="0.1" value="1.6"></label><label>方向<select id="unifiedExportOrientation"><option value="portrait">纵向</option><option value="landscape">横向</option></select></label></div><div class="unified-export-options"><label class="check"><input id="exportIncludeNote" type="checkbox" checked>笔记正文</label><label class="check"><input id="exportAnnotations" type="checkbox" checked>个人补充</label><label class="check"><input id="exportSourceLink" type="checkbox" checked>来源链接</label><label class="check"><input id="exportTimestamps" type="checkbox" checked>时间点</label><label class="check"><input id="exportImages" type="checkbox" checked>图片</label><label class="check"><input id="exportToc" type="checkbox">目录</label><label class="check"><input id="exportTranscript" type="checkbox">完整字幕</label><label class="check"><input id="exportPractice" type="checkbox">学习空间练习</label><label class="check"><input id="exportDiagnostics" type="checkbox">脱敏诊断（Sanitized diagnostics）</label></div><div class="unified-export-actions"><button id="previewUnifiedExport" class="primary">更新预览</button><button id="downloadUnifiedExport">导出文件</button></div><p id="unifiedExportStatus" class="muted" role="status"></p><iframe id="unifiedExportPreview" title="导出预览"></iframe>`);
    dialog.dataset.sourceId = s.id;
    dialog.dataset.sourceKind = s.kind;
    const formatGrid = $("unifiedExportFormat")?.closest(".unified-export-grid");
    const presetBar = document.createElement("div"); presetBar.className = "unified-export-presets";
    presetBar.innerHTML = '<label>导出预设<select id="unifiedExportPreset"><option value="">不使用预设</option></select></label><label>预设名称<input id="unifiedExportPresetName" maxlength="80" placeholder="例如：打印讲义"></label><button type="button" id="saveUnifiedExportPreset">保存当前排版</button><button type="button" id="deleteUnifiedExportPreset" disabled>删除预设</button>';
    formatGrid?.before(presetBar);
    const spacing = document.createElement("div"); spacing.className = "unified-export-spacing";
    spacing.innerHTML = '<label>段前距（pt）<input id="unifiedExportBefore" type="number" min="0" max="60" step="1" value="0"></label><label>段后距（pt）<input id="unifiedExportAfter" type="number" min="0" max="60" step="1" value="7"></label><label>上边距（mm）<input id="unifiedExportTop" type="number" min="5" max="50" step="1" value="18"></label><label>下边距（mm）<input id="unifiedExportBottom" type="number" min="5" max="50" step="1" value="18"></label><label>左边距（mm）<input id="unifiedExportLeft" type="number" min="5" max="50" step="1" value="18"></label><label>右边距（mm）<input id="unifiedExportRight" type="number" min="5" max="50" step="1" value="18"></label>';
    formatGrid?.after(spacing);
    const presetSelect = $("unifiedExportPreset");
    const downloadButton = $("downloadUnifiedExport");
    const statusNode = $("unifiedExportStatus");
    const previewFrame = $("unifiedExportPreview");
    let selectedTemplate = "print", previewSequence = 0, statusSequence = 0, downloading = false;
    const changedPresets = new Set();
    const active = () => token === generation && dialog.open &&
      state.selected?.id === s.id && state.selected?.kind === s.kind;
    const statusText = (message) => { if (active()) statusNode.textContent = message; };
    const warningText = (warnings = []) => {
      const messages = {
        non_bmp_symbols_rendered_as_unicode_names: "PDF 中的部分表情与特殊符号已替换为可读名称，以免显示为空白。",
        docx_toc_page_numbers_require_field_update: "Word 目录页码需要在打开文件后右键目录，选择“更新域/更新整个目录”。",
        claim_citations_require_current_map: "部分结论引用需要按当前笔记重建，请回来源页核对。",
        unrecognized_math_commands_preserved_as_source: "少量公式命令已保留原文，请核对。",
        requested_docx_font_unavailable_using_host_fallback: "所选 Word 字体未安装，将使用打开文件设备上的替代字体；排版可能变化。",
        emoji_font_unavailable_using_host_fallback: "表情字体未安装，将使用打开文件设备上的替代字体。",
        requested_pdf_font_unavailable_using_cjk_fallback: "所选 PDF 字体未安装，已使用中文替代字体；排版可能变化。",
        embedded_system_cjk_font_unavailable_using_pdf_cid_fallback: "未找到可嵌入的中文字体，PDF 已使用兼容字体；请检查中文显示。",
        embedded_html_font_unavailable_using_system_fallback: "离线 HTML 字体无法嵌入，将使用设备上的替代字体。",
      };
      return [...new Set(warnings.map(code => String(code).trim()).filter(Boolean))]
        .map(code => messages[code] || `导出提示：${code}`).join(" ");
    };
    const collect = () => ({
      format: $("unifiedExportFormat").value,
      options: {
        template: selectedTemplate,
        include_note: $("exportIncludeNote").checked,
        include_annotations: $("exportAnnotations").checked,
        include_source_link: $("exportSourceLink").checked,
        include_timestamps: $("exportTimestamps").checked,
        include_images: $("exportImages").checked,
        include_toc: $("exportToc").checked,
        include_transcript: $("exportTranscript").checked,
        include_practice: $("exportPractice").checked,
        include_diagnostics: $("exportDiagnostics").checked,
        font_family: $("unifiedExportFont").value,
        font_size: Number($("unifiedExportSize").value),
        line_height: Number($("unifiedExportLeading").value),
        paragraph_before: Number($("unifiedExportBefore").value),
        paragraph_after: Number($("unifiedExportAfter").value),
        margin_top: Number($("unifiedExportTop").value),
        margin_bottom: Number($("unifiedExportBottom").value),
        margin_left: Number($("unifiedExportLeft").value),
        margin_right: Number($("unifiedExportRight").value),
        orientation: $("unifiedExportOrientation").value,
      },
    });
    const ensureFont = (name) => {
      const select = $("unifiedExportFont");
      if (name && ![...select.options].some(option => option.value === name)) {
        select.append(Object.assign(document.createElement("option"), { value: name, textContent: name }));
      }
    };
    const setOptions = (options = {}) => {
      selectedTemplate = ["print", "academic", "compact"].includes(options.template) ? options.template : "print";
      ensureFont(options.font_family);
      const values = {
        unifiedExportFont: options.font_family, unifiedExportSize: options.font_size,
        unifiedExportLeading: options.line_height, unifiedExportBefore: options.paragraph_before,
        unifiedExportAfter: options.paragraph_after, unifiedExportTop: options.margin_top,
        unifiedExportBottom: options.margin_bottom, unifiedExportLeft: options.margin_left,
        unifiedExportRight: options.margin_right, unifiedExportOrientation: options.orientation,
      };
      Object.entries(values).forEach(([id, value]) => { if (value !== undefined) $(id).value = value; });
      const checks = {
        exportIncludeNote: "include_note", exportAnnotations: "include_annotations",
        exportSourceLink: "include_source_link", exportTimestamps: "include_timestamps",
        exportImages: "include_images", exportToc: "include_toc",
        exportTranscript: "include_transcript", exportPractice: "include_practice",
        exportDiagnostics: "include_diagnostics",
      };
      Object.entries(checks).forEach(([id, key]) => { $(id).checked = Boolean(options[key]); });
    };
    const updateDelete = () => {
      const selected = presetSelect.selectedOptions[0];
      $("deleteUnifiedExportPreset").disabled = !selected?.dataset.name || selected.dataset.readOnly === "true";
    };
    const upsertPreset = (item, builtIn = false) => {
      const value = `${builtIn ? "builtin" : "user"}:${builtIn ? item.id : item.name}`;
      let option = [...presetSelect.options].find(option => option.value === value);
      if (!option) { option = document.createElement("option"); presetSelect.append(option); }
      option.value = value;
      option.textContent = builtIn ? `${item.name}（内置）` : item.name;
      option.dataset.name = item.name;
      option.dataset.readOnly = String(builtIn || item.read_only === true);
      option.dataset.options = JSON.stringify(item.options || {});
      return option;
    };
    api("/api/study/export-presets").then(result => {
      if (!active()) return;
      for (const item of result.built_in_presets || []) upsertPreset(item, true);
      for (const item of result.presets || []) if (!changedPresets.has(item.name)) upsertPreset(item);
      updateDelete();
    }).catch(() => {});
    api("/api/study/export-fonts").then(result => {
      if (!active()) return;
      // Keep a preset's chosen font even when this host lacks it. Export warnings
      // explain fallback rather than silently changing the saved preference.
      for (const item of result.fonts || []) if (item.available) ensureFont(item.name);
    }).catch(() => {});
    presetSelect.addEventListener("change", () => {
      const selected = presetSelect.selectedOptions[0];
      if (selected?.dataset.options) setOptions(JSON.parse(selected.dataset.options));
      else selectedTemplate = "print";
      updateDelete();
    });
    $("saveUnifiedExportPreset").addEventListener("click", async (event) => {
      if (!active() || event.currentTarget.disabled) return;
      const name = $("unifiedExportPresetName").value.trim();
      if (!name) { statusText("请先填写预设名称。"); return; }
      const button = event.currentTarget, settings = collect(), statusToken = ++statusSequence;
      button.disabled = true;
      try {
        const result = await api(`/api/study/export-presets/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(settings) });
        if (!active()) return;
        const item = { name: result.name || name, options: result.options || settings.options };
        changedPresets.add(item.name);
        presetSelect.value = upsertPreset(item).value;
        setOptions(item.options);
        updateDelete();
        if (statusToken === statusSequence) statusText(`已保存导出预设“${item.name}”。`);
      } catch (error) {
        if (statusToken === statusSequence) statusText(error.message);
      } finally { if (active()) button.disabled = false; }
    });
    $("deleteUnifiedExportPreset").addEventListener("click", async (event) => {
      if (!active() || event.currentTarget.disabled) return;
      const selected = presetSelect.selectedOptions[0];
      if (!selected?.dataset.name || selected.dataset.readOnly === "true") {
        statusText("内置预设只读，不能删除；可另存为个人预设。");
        return;
      }
      const name = selected.dataset.name, statusToken = ++statusSequence, button = event.currentTarget;
      button.disabled = true;
      try {
        await api(`/api/study/export-presets/${encodeURIComponent(name)}`, { method: "DELETE" });
        if (!active()) return;
        changedPresets.add(name);
        const wasSelected = presetSelect.value === selected.value;
        selected.remove();
        if (wasSelected) { presetSelect.value = ""; selectedTemplate = "print"; }
        if (statusToken === statusSequence) statusText(`已删除导出预设“${name}”。`);
      } catch (error) {
        if (statusToken === statusSequence) statusText(error.message);
      } finally { if (active()) updateDelete(); }
    });
    const preview = async () => {
      if (!active()) return;
      const sequence = ++previewSequence, statusToken = ++statusSequence;
      statusText("正在整理预览…");
      try {
        const result = await api(`${exportBase}/preview`, { method: "POST", body: JSON.stringify(collect()) });
        if (!active() || sequence !== previewSequence) return;
        previewFrame.srcdoc = result.html;
        if (statusToken === statusSequence) statusText(result.warnings?.length ? `预览已生成。${warningText(result.warnings)}` : "预览已更新；HTML 可离线打开。");
      } catch (error) {
        if (sequence === previewSequence && statusToken === statusSequence) statusText(error.message);
      }
    };
    $("previewUnifiedExport").onclick = preview;
    downloadButton.onclick = async () => {
      if (!active() || downloading) return;
      const settings = collect(), statusToken = ++statusSequence;
      downloading = true;
      downloadButton.disabled = true;
      statusText("正在生成文件…");
      try {
        const response = await fetch(`${exportBase}/${settings.format}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings) });
        if (!active()) return;
        if (!response.ok) throw new Error((await response.text()) || "导出失败");
        const blob = await response.blob();
        if (!active()) return;
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${s.title || "笔记"}.${settings.format}`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        const warnings = warningText((response.headers.get("X-LearnNote-Export-Warning") || "").split(","));
        if (statusToken === statusSequence) statusText(warnings ? `文件已生成。${warnings}` : "文件已生成。");
      } catch (error) {
        if (statusToken === statusSequence) statusText(error.message);
      } finally {
        downloading = false;
        if (active()) downloadButton.disabled = false;
      }
    };
    preview();
  }
  async function annotations() {
    const s = current(),
      token = show("管理我的补充", "<p>正在读取…</p>");
    const result = await api(`/api/personal/${s.kind}/${s.id}`);
    if (token !== generation) return;
    $("toolBody").innerHTML =
      result.annotations
        .map(
          (a) =>
            `<form class="annotation-edit" data-annotation-id="${a.id}"><label>我的补充</label><textarea name="text" required maxlength="8000">${esc(a.text)}</textarea><footer><button>保存</button><button type="button" class="danger" data-delete-annotation="${a.id}">删除这条补充</button></footer></form>`,
        )
        .join("") ||
      "<p>还没有补充。在正文下方写下自己的理解后即可在这里编辑。</p>";
    dialog.dataset.sourceId = s.id;
    dialog.dataset.sourceKind = s.kind;
  }
  function ask() {
    if (window.LearnNoteAssistant) {
      dialog.close();
      window.LearnNoteAssistant.open();
      return;
    }
    const s = current();
    show(
      "围绕当前内容提问",
      `<p class="muted">回答使用当前来源；重要内容仍需回看原文。使用远程模型时会发送必要的材料。</p><form id="askForm"><label for="question">你的问题</label><textarea id="question" required maxlength="1000" placeholder="这段内容中的两个概念有什么区别？"></textarea><button class="primary">查找与回答</button></form><div id="askResult" class="answer"></div>`,
    );
    dialog.dataset.sourceId = s.id;
    dialog.dataset.sourceKind = s.kind;
  }
  function cleanupSummary(result) {
    const items = result.candidates || [];
    if (!items.length) return "没有符合当前规则的旧任务。";
    const size = (bytes) =>
      (Number(bytes || 0) / 1024 / 1024).toFixed(1) + " MB";
    return (
      `${result.dry_run ? "将清理" : "已清理"} ${items.length} 个任务 · ${size(result.dry_run ? result.reclaimable_bytes : result.reclaimed_bytes)}\n\n` +
      items
        .map(
          (item) =>
            `${item.title}\n${String(item.created_at).slice(0, 10)} · ${size(item.bytes)}`,
        )
        .join("\n\n")
    );
  }
  async function storage() {
    cleanupPolicy = null;
    const token = show("存储与诊断", '<p class="muted">正在检查本地存储…</p>');
    const result = await api("/api/storage");
    if (token !== generation) return;
    const formatBytes = (bytes) => {
      const value = Number(bytes || 0);
      if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`;
      return `${(value / 1024 ** 2).toFixed(1)} MB`;
    };
    const upload = result.upload_policy || {};
    const uploadNotice = upload.free_disk_bytes
      ? `上传保护：单个文件 ≤ ${formatBytes(upload.max_video_bytes)}；当前并发预算剩余 ${formatBytes(upload.available_upload_budget_bytes)}；磁盘剩余 ${formatBytes(upload.free_disk_bytes)}（至少保留 ${formatBytes(upload.required_free_disk_bytes)}）。`
      : "上传保护状态暂不可用；提交文件前仍会执行大小和磁盘检查。";
    $("toolBody").innerHTML =
      `<p class="muted">${uploadNotice}</p><p class="muted">清理前先预览范围。学习资料保存在本机，不会因关闭窗口而删除。</p><details><summary>查看本地存储信息</summary><pre>${esc(JSON.stringify(result, null, 2))}</pre></details><div class="tool-actions"><button data-action="open-folder">打开数据文件夹</button><button data-action="backup">备份任务索引</button></div><p class="muted">索引备份不包含视频、文档正文、个人修订或复习数据库；完整备份请复制数据文件夹。</p><details><summary>恢复任务索引</summary><form id="restoreForm"><input id="restoreFile" type="file" accept=".sqlite3" required><button>选择备份并恢复</button></form></details><details><summary>清理旧任务</summary><form id="cleanupForm"><label for="retention">保留最近多少天</label><input id="retention" type="number" min="1" max="3650" value="30"><label for="keepRecent">至少保留最近多少个任务</label><input id="keepRecent" type="number" min="0" max="1000" value="10"><button>预览清理范围</button></form><pre id="cleanupPreview"></pre><button id="executeCleanup" hidden class="danger" data-action="cleanup">确认执行清理</button></details>`;
    await mountSupportSummary($("toolBody"), api);
    backAction = () => {
      dialog.close();
      $("settings").click();
      document.querySelector('[data-settings-section="storage"]')?.click();
    };
  }
  async function diagnostics() {
    const s = current();
    const token = show("这份笔记的处理记录", '<p class="muted">正在读取…</p>');
    const [result, eventResult] = await Promise.all([
      api(`/api/tasks/${s.id}`),
      api(`/api/tasks/${s.id}/events?limit=500`),
    ]);
    if (token !== generation) return;
    const t = result.task;
    $("toolBody").innerHTML =
      `<p><strong>${esc(t.title)}</strong></p>${timelineHtml(t, eventResult.events || [])}${eventLogHtml(eventResult.events || [])}<details><summary>诊断详情与日志下载</summary><p class="muted">当前阶段：${esc(t.phase)} · 错误代码：${esc(t.error_code || "无")}</p>${links(
        [
          ["逐步日志 JSON", `/api/tasks/${s.id}/events?limit=2000`],
          ["脱敏支持包", `/api/tasks/${s.id}/exports/support-package`],
          ["诊断报告", `/api/tasks/${s.id}/exports/diagnostics`],
          ["资源用量", `/api/tasks/${s.id}/exports/resource-usage`],
        ],
      )}<p class="muted">公开分享前检查标题、截图和学习内容。诊断包不等于匿名数据。</p></details>`;
  }
  function more() {
    const s = current();
    show(
      "笔记工具",
      `<div class="tool-menu"><button data-action="exports">导出笔记与原始资料</button><button data-action="propose">创建复习卡</button><button data-action="ask">围绕内容提问</button><button data-action="annotations">管理我的补充</button><button data-action="add-to-course">归入课程</button>${s.kind === "task" ? '<button data-action="regenerate">重新整理视频笔记</button><button data-action="range">学习视频片段</button><button data-action="ocr">查看画面文字</button><button data-action="diagnostics">查看处理记录</button><button data-action="community">独立社区观点</button>' : ""}<button class="danger" data-action="delete-source">删除当前内容</button></div>`,
    );
    if (s.kind === "material" && s.status === "ocr_required") {
      const ocrButton = document.createElement("button");
      ocrButton.dataset.action = "run-material-ocr";
      ocrButton.textContent = "准备扫描 PDF 的本地 OCR";
      $("toolBody").querySelector(".tool-menu")?.append(ocrButton);
    }
    if (s.kind === "material" && !s.linked_task_id) {
      const rebuildButton = document.createElement("button");
      rebuildButton.dataset.action = "rebuild-material";
      rebuildButton.textContent = "从本机原文件重建出处索引";
      $("toolBody").querySelector(".tool-menu")?.append(rebuildButton);
    }
    if (canRedecodeMaterial(s)) {
      const encodingButton = document.createElement("button");
      encodingButton.dataset.action = "material-encoding";
      encodingButton.textContent = "重新选择原文编码";
      $("toolBody").querySelector(".tool-menu")?.append(encodingButton);
    }
    backAction = null;
  }
  async function batch() {
    if (batchRunning) return;
    if (course.paused) throw new Error("请先继续课程。");
    const snapshot = await api(`/api/courses/${course.id}`);
    const pending = (snapshot.episodes || []).filter(item => item.source_kind === "url" && !item.task_id && item.status !== "identity_conflict").slice(0, 24);
    if (!pending.length) { status("没有待提交分集；失败或中断的分集可单独恢复。"); return; }
    if (!confirm(`将提交 ${pending.length} 个分集，字幕优先且不分析画面。每集使用当前资源预算；重复点击会复用已有任务。继续？`)) return;
    batchRunning = true;
    const id = course.id, allowedIds = new Set(pending.map(item=>item.episode_id));
    try {
      for (let submitted=0;submitted<pending.length;submitted++) {
        const fresh = await api(`/api/courses/${id}`);
        if (fresh.course.paused) { status("课程已暂停，剩余分集未提交。"); break; }
        const candidate=(fresh.episodes || []).find(item=>allowedIds.has(item.episode_id)&&!item.task_id&&item.status!=="identity_conflict");
        if(!candidate)break;
        const { episode } = await api(`/api/courses/${id}/episodes/${candidate.episode_id}/prepare`, { method:"POST" });
        if (episode.task_id) continue;
        const task = await api("/api/tasks/from-current-page", { method:"POST", body:JSON.stringify({ page_url:episode.url, title:episode.title, handoff_id:episode.handoff_id, options:{ ...options(), content_mode:"text", visual_understanding:false } }) });
        await api(`/api/courses/${id}/episodes/${candidate.episode_id}/bind`, { method:"POST", body:JSON.stringify({task_id:task.task_id}) });
        status("已提交：" + episode.title);
      }
      await refresh();
      if (course?.id === id && dialog.open) await openCourse(id);
    } finally { batchRunning = false; }
  }
  async function community() {
    const s = current(),
      token = show("社区观点", '<p class="muted">正在读取…</p>');
    const r = await api(`/api/tasks/${s.id}/community-context`);
    if (token !== generation) return;
    dialog.dataset.sourceId = s.id;
    const category = (id) => (r.groups?.questions || []).includes(id) ? "观众问题"
      : (r.groups?.disagreements || []).includes(id) ? "可能存在分歧" : "观众观点";
    $("toolBody").innerHTML =
      `<p class="muted">评论与弹幕是独立观点，不作为课程事实或复习证据。分类仅按关键词提示，不代表事实判断。不会自动抓取网站内容；作者身份默认省略，明显联系方式与推广内容会过滤。</p><button data-action="toggle-community" data-enabled="${r.enabled}">${r.enabled ? "关闭观点层" : "启用观点层"}</button>${r.enabled ? '<form id="communityForm"><label for="communityText">粘贴要保留的观点 · 每行一条</label><textarea id="communityText" required maxlength="20000"></textarea><button>保存观点</button></form>' : ""}<div class="tool-actions">${links([["单独导出社区观点", `/api/tasks/${encodeURIComponent(s.id)}/community-context/export`]])}</div><div class="tool-list">${r.items.map((item) => `<blockquote><small>${category(item.item_id)} · ${item.kind === "danmaku" ? "弹幕" : "评论"}${item.timestamp_seconds === null ? "" : " · " + Number(item.timestamp_seconds) + " 秒"}</small><p>${esc(item.text)}</p><button data-action="delete-community-item" data-item-id="${esc(item.item_id)}">删除这条观点</button></blockquote>`).join("")}</div><button class="danger" data-action="clear-community">清空本任务观点</button>`;
  }

  function relationshipGraph(result) {
    const nodes = (result.nodes || []).slice(0, 24);
    const edges = (result.edges || []).filter((edge) => nodes.some((node) => node.id === edge.from) && nodes.some((node) => node.id === edge.to));
    if (!nodes.length || !edges.length) return null;
    const width = 760, cellWidth = 180, cellHeight = 86, columns = 4;
    const height = Math.max(180, Math.ceil(nodes.length / columns) * cellHeight + 32);
    const position = new Map(nodes.map((node, index) => [node.id, { x: 16 + (index % columns) * cellWidth, y: 16 + Math.floor(index / columns) * cellHeight }]));
    const details = document.createElement("details");
    details.className = "relationship-graph";
    const summary = document.createElement("summary");
    summary.textContent = "关系图（关键词线索，不代表因果或观点一致）";
    details.append(summary);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "课程来源关系图");
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = "课程来源关系图";
    svg.append(title);
    for (const edge of edges) {
      const from = position.get(edge.from), to = position.get(edge.to);
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(from.x + 72)); line.setAttribute("y1", String(from.y + 25));
      line.setAttribute("x2", String(to.x + 72)); line.setAttribute("y2", String(to.y + 25));
      line.setAttribute("class", "relationship-edge");
      line.setAttribute("aria-label", `共同关键词：${(edge.terms || []).join("、")}`);
      svg.append(line);
    }
    for (const node of nodes) {
      const point = position.get(node.id);
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", String(point.x)); rect.setAttribute("y", String(point.y));
      rect.setAttribute("width", "144"); rect.setAttribute("height", "50"); rect.setAttribute("rx", "8");
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", String(point.x + 8)); label.setAttribute("y", String(point.y + 22));
      label.textContent = String(node.title || node.id).slice(0, 22);
      const count = document.createElementNS("http://www.w3.org/2000/svg", "text");
      count.setAttribute("x", String(point.x + 8)); count.setAttribute("y", String(point.y + 40));
      count.setAttribute("class", "relationship-node-meta");
      count.textContent = `${(node.evidence_ids || []).length} 条来源证据`;
      group.append(rect, label, count); svg.append(group);
    }
    details.append(svg);
    const hint = document.createElement("p");
    hint.className = "muted";
    hint.textContent = "图下方的关系列表保留每条关系对应的证据 ID；无法理解图形时可直接使用列表。";
    details.append(hint);
    return details;
  }
  async function about() {
    const token = show("关于与更新", "<p>正在读取版本信息…</p>");
    const h = await api("/health");
    if (token !== generation) return;
    $("toolBody").innerHTML =
      `<h3>LearnNote ${esc(h.app_version)}</h3><p>统一阅读工作台 · 数据保存在本机</p><button data-action="check-update">检查正式发布版</button><p id="updateResult" role="status"></p><a class="tool-link" href="https://github.com/hurry060215-tech/learnnote-assistant/releases/latest" target="_blank" rel="noreferrer">打开官方下载页 ↗</a>`;
  }
  const ocrMaterial = async () => {
    const s = current();
    if (!confirm("使用本机可选 OCR 读取扫描 PDF？OCR 结果会保留置信度并标为未核验。")) return;
    const result = await api("/api/library/materials/" + encodeURIComponent(s.id) + "/ocr", { method: "POST" });
    await refresh();
    notice(result.ocr?.warning || "扫描 PDF OCR 已完成，请核对每页文字。");
    more();
  };
  const actions = {
    "material-encoding": materialEncoding,
    community,
    "toggle-community": async (button) => {
      await api("/api/study/community/settings", {
        method: "PUT",
        body: JSON.stringify({ enabled: button.dataset.enabled !== "true" }),
      });
      await community();
    },
    "delete-community-item": async (button) => {
      if (!confirm("删除这条社区观点？")) return;
      await api(`/api/tasks/${encodeURIComponent(dialog.dataset.sourceId)}/community-context/${encodeURIComponent(button.dataset.itemId)}`, { method: "DELETE" });
      await community();
    },
    "clear-community": async () => {
      if (confirm("清空当前任务的社区观点？")) {
        await api(
          `/api/tasks/${dialog.dataset.sourceId}/community-context?confirm=clear_community_context`,
          { method: "DELETE" },
        );
        await community();
      }
    },
    "check-update": async () => {
      if (!window.pywebview?.api?.check_update) {
        $("updateResult").textContent = "请打开官方下载页查看最新正式版。";
        return;
      }
      const r = await window.pywebview.api.check_update();
      $("updateResult").textContent = r.ok
        ? `最新正式版：${r.latest_version}。当前预览版可能比正式版更新。`
        : "暂时无法检查更新，请使用官方下载页。";
    },

    "run-material-ocr": ocrMaterial,
    "rebuild-material": async () => {
      const selected = current();
      const token = generation;
      const result = await api(`/api/library/materials/${encodeURIComponent(selected.id)}/rebuild`, { method: "POST" });
      await refresh();
      if (token !== generation || state.selected?.id !== selected.id || state.selected?.kind !== selected.kind) return;
      await openItem({ ...selected, ...result.material, id: selected.id, kind: "material" });
      if (token !== generation || state.selected?.id !== selected.id || state.selected?.kind !== selected.kind) return;
      notice(`已从本机原文件恢复 ${result.material.anchor_count} 条出处；现有引用 ID 保留。`);
      more();
    },
    regenerate: () => {
      dialog.close();
      $("regenerate").click();
    },
    courses: listCourses,
    "new-course": () => {
      course = null;
      courseEditor();
    },
    "edit-course": courseEditor,
    "pause-course": async () => {
      await saveCourse({ ...course, paused: !course.paused });
      courseView();
    },
    "delete-course": async () => {
      if (!confirm("只删除课程分组，保留其中的笔记和资料？")) return;
      await api(`/api/courses/${course.id}`, { method: "DELETE" });
      course = null;
      await listCourses();
    },
    batch,
    "course-review": () => studySettings(course.id),
    "refresh-course": () => openCourse(course.id),
    "resume-study": async (button) => {
      const { plan } = await api("/api/study/plan");
      await api("/api/study/plan", { method: "PUT", body: JSON.stringify({ title: plan.title, daily_target: plan.daily_target, timezone: plan.timezone, paused: false }) });
      await studySettings(button.dataset.courseId || "",button.dataset.taskId || "");
    },
    "start-review": async (button) => {
      dialog.close();
      await ctx.startReview(button.dataset.courseId || "",button.dataset.taskId || "");
    },
    "range-position": () => {
      $("rangeStart").value = Math.floor($("player").currentTime || 0);
    },
    "run-ocr": async () => {
      if (!confirm("使用缓存视频创建一份开启本地 OCR 的新笔记？")) return;
      const result = await api(
        `/api/tasks/${dialog.dataset.sourceId}/rerun-from-media`,
        {
          method: "POST",
          body: JSON.stringify({ ...options(), local_ocr: true }),
        },
      );
      dialog.close();
      await openItem({ ...result.task, id: result.task_id, kind: "task" });
      await refresh();
    },
    "rebuild-study": async () => {
      if (confirm("按完整评分历史重建复习调度？当前调度会先备份。")) {
        await api("/api/study/rebuild-schedule?confirm=rebuild_from_history", {
          method: "POST",
        });
        status("调度已重建。");
      }
    },
    "open-folder": async () => {
      if (window.pywebview?.api?.open_data_folder)
        await window.pywebview.api.open_data_folder();
      else
        status(
          "请在桌面客户端打开数据文件夹；浏览器模式请查看存储信息中的路径。",
        );
    },
    backup: async () => {
      const r = await api("/api/library/backup", { method: "POST" });
      $("toolBody").insertAdjacentHTML(
        "beforeend",
        links([["下载索引备份", r.download_url]]),
      );
    },
    cleanup: async () => {
      if (!cleanupPolicy)
        throw new Error("请先预览清理范围。修改规则后需要重新预览。");
      if (!confirm("永久删除预览范围中的旧任务及其文件？")) return;
      const r = await api("/api/storage/cleanup", {
        method: "POST",
        body: JSON.stringify({
          ...cleanupPolicy,
          dry_run: false,
        }),
      });
      $("cleanupPreview").textContent = cleanupSummary(r);
      $("executeCleanup").hidden = true;
      await refresh();
    },
    playlist: async () => {
      const r = await api("/api/courses/playlist-preview", {
        method: "POST",
        body: JSON.stringify({ url: $("playlistUrl").value }),
      });
      $("playlistResult").innerHTML =
        `<p>找到 ${r.sources.length} 个链接，保存课程后才会提交处理。</p>`;
      $("courseLinks").value = [
        $("courseLinks").value,
        ...r.sources.map((s) => s.url),
      ]
        .filter(Boolean)
        .join("\n");
    },
    "learn-full-source": async () => {
      const source = await fullVideoSource(dialog.dataset.sourceId, id => api(`/api/tasks/${encodeURIComponent(id)}`));
      if (!confirm(`使用已保存的完整原视频“${source.title}”和当前模型设置创建全片笔记？`)) return;
      const result = await api(`/api/tasks/${encodeURIComponent(source.id)}/rerun-from-media`, { method: "POST", body: JSON.stringify(options()) });
      dialog.close();
      await refresh();
      await openItem({ ...result.task, id: result.task_id, kind: "task" });
    },
    "add-to-course": async () => {
      const s = current();
      const r = await api("/api/courses");
      show(
        "将当前笔记归入课程",
        r.courses
          .map(
            (c) =>
              `<button class="tool-row" data-add-course="${c.id}">${esc(c.title)}</button>`,
          )
          .join("") ||
          '<p>还没有课程。</p><button data-action="new-course">新建课程</button>',
      );
      dialog.dataset.sourceId = s.id;
      dialog.dataset.sourceKind = s.kind;
    },
    "delete-source": async () => {
      const s = current();
      if (
        !guard() ||
        !confirm("永久删除这份内容及其本地文件？请先导出需要保留的修改。")
      )
        return;
      await api(
        s.kind === "task"
          ? `/api/tasks/${s.id}`
          : `/api/library/materials/${s.id}?confirm=delete_material`,
        { method: "DELETE" },
      );
      dialog.close();
      location.href = "/";
    },
    exports,
    propose,
    range,
    ocr,
    ask,
    annotations,
    diagnostics,
  };
  dialog.addEventListener("click", (event) => {
    const b = event.target.closest("button,a");
    if (!b) return;
    if (b.hasAttribute("data-tool-back")) {
      if (window.LearnNoteDialogs && !window.LearnNoteDialogs.canLeave(dialog))
        return;
      window.LearnNoteDialogs?.markSaved(dialog);
      if (backAction) run(b, backAction);
      else dialog.close();
      return;
    }
    if (b.hasAttribute("data-close-tool")) {
      generation++;
      dialog.close();
      return;
    }
    if (b.dataset.action) {
      event.preventDefault();
      run(b, () => actions[b.dataset.action]?.(b));
    } else if (b.dataset.course) run(b, () => openCourse(b.dataset.course));
    else if (b.dataset.move !== undefined)
      run(b, async () => {
        const i = Number(b.dataset.move),
          j = i + Number(b.dataset.direction);
        const sources = [...course.sources];
        [sources[i], sources[j]] = [sources[j], sources[i]];
        await saveCourse({ ...course, sources });
        courseView();
      });
    else if (b.dataset.retryEpisode)
      run(b, async () => {
        if (!confirm("从此分集已有媒体和检查点恢复？使用当前模型设置，不创建重复分集。")) return;
        const { episode } = await api(`/api/courses/${course.id}/episodes/${b.dataset.retryEpisode}/prepare`, { method:"POST" });
        if (!episode.retryable || !episode.task_id) { await openCourse(course.id); return; }
        await api(episode.resume_endpoint, { method:"POST", body:JSON.stringify(options()) });
        await openCourse(course.id);
        await refresh();
      });
    else if (b.dataset.openSource !== undefined)
      run(b, async () => {
        const source = course.sources[Number(b.dataset.openSource)];
        const episode = courseEpisodes.find(item => item.position === Number(b.dataset.openSource));
        const sourceId = source.kind === "url" ? episode?.task_id : source.id;
        const sourceKind = source.kind === "url" ? "task" : source.kind;
        if (!sourceId) { status("点击“整理待处理链接”开始生成笔记。"); return; }
        const item = state.items.find(i => i.id === sourceId && i.kind === sourceKind);
        if (!item) throw new Error("来源已被删除或不在当前资料库。");
        dialog.close();
        await openItem(item);
      });
    else if (b.dataset.evidence)
      run(b, async () => {
        dialog.close();
        await ctx.openEvidence(b.dataset.evidence);
      });
    else if (b.dataset.addCourse)
      run(b, async () => {
        const r = await api(`/api/courses/${b.dataset.addCourse}`);
        course = r.course;
        const s = state.items.find(
          (i) =>
            i.id === dialog.dataset.sourceId &&
            i.kind === dialog.dataset.sourceKind,
        );
        await saveCourse({
          ...course,
          sources: [
            ...course.sources,
            { kind: s.kind, id: s.id, title: s.title },
          ],
        });
        courseView();
      });
    else if (b.dataset.export)
      run(b, async () => {
        const url = `/api/tasks/editions/${dialog.dataset.sourceKind}/${dialog.dataset.sourceId}/exports/${b.dataset.export}?include_annotations=${$("exportAnnotations").checked}`;
        const response = await fetch(url);
        if (!response.ok) {
          const data = await response.json();
          throw new Error(data.detail?.message || data.detail || "导出失败");
        }
        const blob = await response.blob(),
          link = document.createElement("a"),
          object = URL.createObjectURL(blob);
        link.href = object;
        link.download = `笔记.${b.dataset.export === "markdown" ? "md" : b.dataset.export}`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(object), 1000);
      });
    else if (b.dataset.deleteAnnotation)
      run(b, async () => {
        if (!confirm("删除这条补充？")) return;
        await api(
          `/api/personal/${dialog.dataset.sourceKind}/${dialog.dataset.sourceId}/${b.dataset.deleteAnnotation}`,
          { method: "DELETE" },
        );
        await annotations();
        ctx.reloadAnnotations();
      });
  });
  dialog.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.target;
    run(event.submitter, async (token) => {
      if (form.id === "communityForm") {
        await api(`/api/tasks/${dialog.dataset.sourceId}/community-context`, {
          method: "POST",
          body: JSON.stringify({
            items: $("communityText")
              .value.split(/\n/)
              .map((text) => text.trim())
              .filter(Boolean)
              .map((text) => ({ kind: "comment", text })),
          }),
        });
        await community();
      } else if (form.id === "courseForm") {
        const checked = [...form.querySelectorAll("[data-source]:checked")]
          .map((el) =>
            state.items.find(
              (i) => i.id === el.dataset.source && i.kind === el.dataset.kind,
            ),
          )
          .map((s) => ({ kind: s.kind, id: s.id, title: s.title }));
        const selected = new Map(checked.map((s) => [s.kind + ":" + s.id, s]));
        const ordered = (course?.sources || []).filter(
          (s) => s.kind !== "url" && selected.has(s.kind + ":" + s.id),
        );
        const known = new Set(ordered.map((s) => s.kind + ":" + s.id));
        const sources = [
          ...ordered,
          ...checked.filter((s) => !known.has(s.kind + ":" + s.id)),
          ...$("courseLinks")
            .value.split(/\n/)
            .map((s) => s.trim())
            .filter(Boolean)
            .map((url) => ({ kind: "url", url, title: url })),
        ];
        await saveCourse({
          title: $("courseTitle").value,
          sources,
          paused: course?.paused || false,
        });
        courseView();
      } else if (form.id === "compareForm") {
        const filters = new URLSearchParams({ q: $("compareQuery").value, source_kind: $("compareSourceKind").value, source_id: $("compareSourceId").value });
        if ($("compareStart").value !== "") filters.set("start", $("compareStart").value);
        if ($("compareEnd").value !== "") filters.set("end", $("compareEnd").value);
        const r = await api(`/api/courses/${course.id}/compare?${filters}`);
        if (token !== generation) return;
        $("compareResults").innerHTML =
          `<p class="muted">${esc(r.warning)}</p>${r.matches.map((m) => `<blockquote><strong>${esc(m.title)}</strong><small>${esc(m.locator)}</small><p>${esc(m.excerpt)}</p><button data-evidence="${esc(m.evidence_id)}">核对出处</button></blockquote>`).join("") || "没有匹配出处。"}`;
        if (form.id === "compareForm" && r.edges?.length) {
          const graphView = relationshipGraph(r);
          if (graphView) $("compareResults").append(graphView);
          const graph = document.createElement("details");
          const graphTitle = document.createElement("summary");
          graphTitle.textContent = "关系列表（每条关系保留来源）";
          graph.append(graphTitle);
          const list = document.createElement("ol");
          const nodes = new Map((r.nodes || []).map((node) => [node.id, node.title]));
          for (const edge of r.edges) {
            const item = document.createElement("li");
            item.textContent = (nodes.get(edge.from) || edge.from) + " ↔ " + (nodes.get(edge.to) || edge.to) + " · 共同关键词：" + (edge.terms || []).join("、") + " · 证据：" + (edge.evidence_ids || []).join("、");
            list.append(item);
          }
          graph.append(list);
          $("compareResults").append(graph);
        }
      } else if (form.id === "planForm") {
        await api("/api/study/plan", {
          method: "PUT",
          body: JSON.stringify({
            daily_target: Number($("dailyTarget").value),
            timezone: $("studyTimezone").value,
            paused: $("studyPaused").checked,
          }),
        });
        status("复习计划已保存。");
      } else if (form.id === "cardsForm") {
        const cards = [
          ...form.querySelectorAll("[data-card-index]:checked"),
        ].map((el) => {
          const i = Number(el.dataset.cardIndex);
          return {
            ...proposals[i],
            front: $("front" + i).value,
            back: $("back" + i).value,
          };
        });
        await api("/api/study/cards", {
          method: "POST",
          body: JSON.stringify({ cards }),
        });
        status(`已加入 ${cards.length} 张卡片。`);
        form
          .querySelectorAll("input,textarea,button")
          .forEach((el) => (el.disabled = true));
      } else if (form.id === "rangeForm") {
        const start = Number($("rangeStart").value),
          end = Number($("rangeEnd").value);
        if (end <= start) throw new Error("结束位置必须晚于开始位置。");
        const r = await api(
          `/api/tasks/${dialog.dataset.sourceId}/learn-range`,
          {
            method: "POST",
            body: JSON.stringify({ start, end, options: options() }),
          },
        );
        dialog.close();
        await openItem({ ...r.task, id: r.task_id, kind: "task" });
        await refresh();
      } else if (form.id === "askForm") {
        const s = {
            id: dialog.dataset.sourceId,
            kind: dialog.dataset.sourceKind,
          },
          question = $("question").value;
        const r =
          s.kind === "task"
            ? await api(`/api/tasks/${s.id}/qa`, {
                method: "POST",
                body: JSON.stringify({ question, options: options() }),
              })
            : await api(`/api/library/materials/${s.id}/ask`, {
                method: "POST",
                body: JSON.stringify({ question }),
              });
        if (token !== generation) return;
        $("askResult").textContent =
          r.answer || r.message || JSON.stringify(r, null, 2);
      } else if (form.id === "restoreForm") {
        if (!confirm("恢复所选任务索引？当前索引会先备份，文档和证据保留。"))
          return;
        const data = new FormData();
        data.append("file", $("restoreFile").files[0]);
        await api("/api/library/restore", { method: "POST", body: data });
        status("索引已恢复。");
        await refresh();
      } else if (form.id === "cleanupForm") {
        const r = await api("/api/storage/cleanup", {
          method: "POST",
          body: JSON.stringify({
            retention_days: Number($("retention").value),
            keep_recent: Number($("keepRecent").value),
            dry_run: true,
          }),
        });
        $("cleanupPreview").textContent = cleanupSummary(r);
        cleanupPolicy = {
          retention_days: Number($("retention").value),
          keep_recent: Number($("keepRecent").value),
        };
        $("executeCleanup").hidden = !r.candidates?.length;
      } else if (form.dataset.annotationId) {
        await api(
          `/api/personal/${dialog.dataset.sourceKind}/${dialog.dataset.sourceId}`,
          {
            method: "POST",
            body: JSON.stringify({
              id: form.dataset.annotationId,
              text: form.elements.text.value,
            }),
          },
        );
        window.LearnNoteDialogs?.markSaved(dialog);
        status("补充已更新。");
        ctx.reloadAnnotations();
      }
    });
  });
  dialog.addEventListener("input", (event) => {
    if (event.target.closest("#cleanupForm")) {
      cleanupPolicy = null;
      $("executeCleanup").hidden = true;
    }
  });
  dialog.addEventListener("learnnote:dialog-closed", () => {
    generation++;
  });
  dialog.addEventListener("cancel", () => {
    generation++;
  });
  const courseButton = document.createElement("button");
  courseButton.id = "courses";
  courseButton.textContent = "学习空间";
  document.querySelector(".sidebar footer").prepend(courseButton);
  courseButton.onclick = () => {
    if (window.LearnNoteLearningSpaces) {
      window.LearnNoteLearningSpaces.open({
        currentSource: () => state.selected ? { kind: state.selected.kind, id: state.selected.id, title: state.selected.title } : null,
        availableSources: () => state.items.map(item => ({ kind: item.kind, id: item.id, title: item.title })),
        onOpenSource: (source) => openItem(source).catch((e) => notice(e.message)),
      }).catch((e) => notice(e.message));
    } else listCourses().catch((e) => notice(e.message));
  };
  $("review").hidden = true;
  const moreButton = document.createElement("button");
  moreButton.id = "moreTools";
  moreButton.textContent = "更多";
  $("noteActions").append(moreButton);
  moreButton.onclick = more;
  $("export").onclick = exports;
  $("export").hidden = true;
  $("regenerate").classList.add("tool-only");
  const settingsTools = $("settingsDialog").querySelector("details");
  settingsTools.innerHTML =
    '<summary>数据与学习管理</summary><div class="tool-actions"><button type="button" id="storageTools">存储与诊断</button><button type="button" id="studyTools">复习计划</button><button type="button" id="aboutTools">关于与更新</button></div>';
  $("storageTools").onclick = () => {
    $("settingsDialog").close();
    storage().catch((e) => notice(e.message));
  };
  $("studyTools").onclick = () => {
    $("settingsDialog").close();
    studySettings().catch((e) => notice(e.message));
  };
  $("aboutTools").onclick = () => {
    $("settingsDialog").close();
    about().catch((e) => notice(e.message));
  };
  const setup = document.createElement("button");
  setup.type = "button";
  setup.id = "setupExtension";
  setup.textContent = "连接浏览器扩展";
  $("browserInput").append(setup);
  setup.onclick = async () => {
    setup.disabled = true;
    try {
      if (window.pywebview?.api?.setup_browser_extension) {
        const r = await window.pywebview.api.setup_browser_extension();
        notice(r.message || "已打开扩展设置");
      } else notice("请安装扩展并保持桌面客户端运行，在扩展中连接本机服务。");
    } catch (e) {
      notice(e.message);
    } finally {
      setup.disabled = false;
    }
  };
  const prefs = document.createElement("label");
  prefs.className = "check";
  prefs.innerHTML =
    '<input id="localOcr" type="checkbox">本地识别画面文字（OCR）';
  $("generationOptions").append(prefs);
  const questionPreference = document.createElement("label");
  questionPreference.className = "check";
  questionPreference.innerHTML = '<input id="generateQuestions" type="checkbox">本次明确生成自测题（题目独立于笔记正文）';
  $("generationOptions").append(questionPreference);
  return { listCourses, studySettings, storage, diagnostics, ocr };
}
