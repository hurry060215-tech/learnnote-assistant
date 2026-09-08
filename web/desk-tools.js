import { eventLogHtml, timelineHtml } from "/web/desk-progress.js";
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
    courseView();
  }
  function courseView() {
    show(
      course.title,
      `<div class="tool-actions"><button data-action="courses">所有课程</button><button data-action="edit-course">编辑来源</button><button data-action="pause-course">${course.paused ? "继续课程" : "暂停课程"}</button><button data-action="batch" ${course.paused ? "disabled" : ""}>整理待处理链接</button></div><div class="tool-list">${course.sources.map((s, i) => `<div class="tool-row"><button class="grow" data-open-source="${i}"><strong>${esc(s.title || s.url || s.id)}</strong><small>${s.kind === "url" ? "待整理链接" : s.kind === "task" ? "视频笔记" : "学习资料"}</small></button><button data-move="${i}" data-direction="-1" aria-label="上移" ${i === 0 ? "disabled" : ""}>↑</button><button data-move="${i}" data-direction="1" aria-label="下移" ${i === course.sources.length - 1 ? "disabled" : ""}>↓</button></div>`).join("")}</div><details><summary>对照不同来源</summary><form id="compareForm"><label for="compareQuery">查找共同讨论的内容</label><input id="compareQuery" required placeholder="输入关键词"><button>查找出处</button></form><div id="compareResults"></div></details><footer><button data-action="course-review">复习这门课程</button><button class="danger" data-action="delete-course">删除课程分组</button></footer>`,
    );
    backAction = listCourses;
  }
  async function studySettings(courseId = "") {
    const token = show("复习与计划", '<p class="muted">正在读取…</p>');
    await api("/api/study/plan/initialize", {
      method: "POST",
      body: JSON.stringify({
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }),
    });
    const [plan, history] = await Promise.all([
      api("/api/study/plan"),
      api("/api/study/reviews?limit=20"),
    ]);
    if (token !== generation) return;
    const p = plan.plan;
    $("toolBody").innerHTML =
      `<form id="planForm"><label for="dailyTarget">每日目标</label><input id="dailyTarget" type="number" min="1" max="200" value="${p.daily_target}"><label for="studyTimezone">复习时区</label><input id="studyTimezone" value="${esc(p.timezone)}" required><label class="check"><input id="studyPaused" type="checkbox" ${p.paused ? "checked" : ""}>暂停复习提醒与评分</label><button class="primary">保存计划</button></form><div class="tool-actions"><button data-action="start-review" data-course-id="${esc(courseId)}">开始复习${courseId ? "当前课程" : ""}</button>${links([["导出学习记录", "/api/study/export"]])}</div><details><summary>最近评分记录</summary><div>${history.reviews.map((r) => `<p class="record">${esc(r.reviewed_at || r.created_at || "")} · 评分 ${esc(r.rating)}</p>`).join("") || '<p class="muted">还没有评分记录。</p>'}</div></details><details><summary>修复旧版复习调度</summary><p class="muted">根据完整评分历史重新计算计划，并在本地保存原调度备份。</p><button data-action="rebuild-study">按历史重建</button></details>`;
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
      `<p class="muted">起止位置以当前视频的秒数计算。新片段会创建独立笔记。</p><form id="rangeForm"><label for="rangeStart">开始（秒）</label><input id="rangeStart" type="number" min="0" step="0.1" required value="${Math.floor($("player").currentTime || 0)}"><label for="rangeEnd">结束（秒）</label><input id="rangeEnd" type="number" min="0.1" step="0.1" required><button type="button" data-action="range-position">用当前播放位置填入开始</button><footer><button class="primary">整理此片段</button></footer></form>`,
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
    show(
      "导出笔记与来源",
      `<p>导出使用已保存的个人修订稿。先保存正文中的修改，再导出。</p><label class="check"><input id="exportAnnotations" type="checkbox" checked>附上我的补充</label><div class="tool-actions">${["markdown", "docx", "pdf"].map((format) => `<button data-export="${format}">${{ markdown: "Markdown", docx: "Word 文档", pdf: "PDF" }[format]}</button>`).join("")}</div>${
        s.kind === "task"
          ? `<details><summary>原始资料与集成</summary>${links([
              ["原始生成稿", `/api/tasks/${s.id}/exports/markdown`],
              ["字幕", `/api/tasks/${s.id}/exports/subtitles`],
              ["视频", `/api/tasks/${s.id}/exports/media`],
              ["完整资料包", `/api/tasks/${s.id}/exports/bundle`],
              ["Notion 数据", `/api/tasks/${s.id}/exports/notion`],
              ["集成清单", `/api/tasks/${s.id}/exports/manifest`],
            ])}<p class="muted">资料包和集成清单保留生成稿；个人修订稿请用上方按钮另存。</p></details>`
          : links([["原始文件", `/api/library/materials/${s.id}/source`]])
      }`,
    );
    dialog.dataset.sourceId = s.id;
    dialog.dataset.sourceKind = s.kind;
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
    $("toolBody").innerHTML =
      `<p class="muted">清理前先预览范围。学习资料保存在本机，不会因关闭窗口而删除。</p><details><summary>查看本地存储信息</summary><pre>${esc(JSON.stringify(result, null, 2))}</pre></details><div class="tool-actions"><button data-action="open-folder">打开数据文件夹</button><button data-action="backup">备份任务索引</button></div><p class="muted">索引备份不包含视频、文档正文、个人修订或复习数据库；完整备份请复制数据文件夹。</p><details><summary>恢复任务索引</summary><form id="restoreForm"><input id="restoreFile" type="file" accept=".sqlite3" required><button>选择备份并恢复</button></form></details><details><summary>清理旧任务</summary><form id="cleanupForm"><label for="retention">保留最近多少天</label><input id="retention" type="number" min="1" max="3650" value="30"><label for="keepRecent">至少保留最近多少个任务</label><input id="keepRecent" type="number" min="0" max="1000" value="10"><button>预览清理范围</button></form><pre id="cleanupPreview"></pre><button id="executeCleanup" hidden class="danger" data-action="cleanup">确认执行清理</button></details>`;
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
    backAction = null;
  }
  async function batch() {
    if (batchRunning) return;
    if (course.paused) throw new Error("请先继续课程。");
    const urls = course.sources.filter((s) => s.kind === "url");
    if (!urls.length) {
      status("没有待整理链接。");
      return;
    }
    if (
      !confirm(
        `将提交前 ${Math.min(24, urls.length)} 个链接，并使用当前模型设置。继续？`,
      )
    )
      return;
    batchRunning = true;
    const id = course.id;
    try {
      for (const source of urls.slice(0, 24)) {
        const fresh = (await api(`/api/courses/${id}`)).course;
        if (fresh.paused) {
          status("课程已暂停，剩余链接未提交。");
          break;
        }
        const index = fresh.sources.findIndex(
          (s) => s.kind === "url" && s.url === source.url,
        );
        if (index < 0) continue;
        const digest = await crypto.subtle.digest(
          "SHA-256",
          new TextEncoder().encode(id + ":" + source.url),
        );
        const handoff =
          "course-" +
          [...new Uint8Array(digest)]
            .map((x) => x.toString(16).padStart(2, "0"))
            .join("")
            .slice(0, 40);
        const task = await api("/api/tasks/from-current-page", {
          method: "POST",
          body: JSON.stringify({
            page_url: source.url,
            title: source.title,
            handoff_id: handoff,
            options: options(),
          }),
        });
        fresh.sources[index] = {
          kind: "task",
          id: task.task_id,
          title: source.title,
        };
        const saved = await api(`/api/courses/${id}`, {
          method: "PUT",
          body: JSON.stringify({
            title: fresh.title,
            sources: fresh.sources,
            paused: fresh.paused,
            revision: fresh.revision,
          }),
        });
        if (course?.id === id) course = saved.course;
        if (dialog.open && generation) status("已提交：" + source.title);
      }
      await refresh();
      if (course?.id === id && dialog.open) courseView();
    } finally {
      batchRunning = false;
    }
  }
  async function community() {
    const s = current(),
      token = show("社区观点", '<p class="muted">正在读取…</p>');
    const r = await api(`/api/tasks/${s.id}/community-context`);
    if (token !== generation) return;
    dialog.dataset.sourceId = s.id;
    $("toolBody").innerHTML =
      `<p class="muted">评论与弹幕是独立观点，不作为课程事实或复习证据。不会自动抓取网站内容。</p><button data-action="toggle-community" data-enabled="${r.enabled}">${r.enabled ? "关闭观点层" : "启用观点层"}</button>${r.enabled ? '<form id="communityForm"><label for="communityText">粘贴要保留的观点 · 每行一条</label><textarea id="communityText" required maxlength="20000"></textarea><button>保存观点</button></form>' : ""}<div class="tool-list">${r.items.map((item) => `<blockquote><small>${esc(item.kind)}</small><p>${esc(item.text)}</p></blockquote>`).join("")}</div><button class="danger" data-action="clear-community">清空本任务观点</button>`;
  }
  async function about() {
    const token = show("关于与更新", "<p>正在读取版本信息…</p>");
    const h = await api("/health");
    if (token !== generation) return;
    $("toolBody").innerHTML =
      `<h3>LearnNote ${esc(h.app_version)}</h3><p>统一阅读工作台 · 数据保存在本机</p><button data-action="check-update">检查正式发布版</button><p id="updateResult" role="status"></p><a class="tool-link" href="https://github.com/hurry060215-tech/learnnote-assistant/releases/latest" target="_blank" rel="noreferrer">打开官方下载页 ↗</a>`;
  }
  const actions = {
    community,
    "toggle-community": async (button) => {
      await api("/api/study/community/settings", {
        method: "PUT",
        body: JSON.stringify({ enabled: button.dataset.enabled !== "true" }),
      });
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
    "start-review": async (button) => {
      dialog.close();
      await ctx.startReview(button.dataset.courseId || "");
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
    else if (b.dataset.openSource !== undefined)
      run(b, async () => {
        const source = course.sources[Number(b.dataset.openSource)];
        if (source.kind === "url") {
          status("点击“整理待处理链接”开始生成笔记。");
          return;
        }
        const item = state.items.find(
          (i) => i.id === source.id && i.kind === source.kind,
        );
        if (!item) throw new Error("来源已被删除或不在当前资料库。");
        dialog.close();
        await openItem(item);
      });
    else if (b.dataset.evidence)
      run(b, async () => {
        const r = await api(`/api/knowledge/evidence/${b.dataset.evidence}`);
        const p = document.createElement("p");
        p.className = "source-excerpt";
        p.textContent = `${r.evidence.title} · ${r.evidence.locator}\n${r.evidence.text}`;
        b.after(p);
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
        const r = await api(
          `/api/courses/${course.id}/compare?q=${encodeURIComponent($("compareQuery").value)}`,
        );
        if (token !== generation) return;
        $("compareResults").innerHTML =
          `<p class="muted">${esc(r.warning)}</p>${r.matches.map((m) => `<blockquote><strong>${esc(m.title)}</strong><small>${esc(m.locator)}</small><p>${esc(m.excerpt)}</p></blockquote>`).join("") || "没有匹配出处。"}`;
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
  courseButton.textContent = "课程";
  document.querySelector(".sidebar footer").prepend(courseButton);
  courseButton.onclick = () => listCourses().catch((e) => notice(e.message));
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
  return { listCourses, studySettings, storage, diagnostics, ocr };
}
