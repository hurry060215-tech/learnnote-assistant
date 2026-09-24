import {
  installConnections,
  loadModelConnection,
} from "/web/desk-connections.js";
import { timelineHtml, taskExplanation } from "/web/desk-progress.js";
import { installInteractions } from "/web/desk-interactions.js";
import { installLayout } from "/web/desk-layout.js";
import { installProfile } from "/web/desk-profile.js";
import { createTaskEventHub } from "/web/desk-events.js";
import { sourceVideoEmbed } from "/web/source-video.js";
import { installSettings } from "/web/desk-settings.js";
import { installProductWorkspace } from "/web/desk-product.js?v=first-run-20260923";
import { installTools } from "/web/desk-tools.js?v=0.2.14";
import {
  api,
  escapeHtml as esc,
  timestamp,
  timestampRanges,
  taskAsset,
} from "/web/desk-api.js";
const $ = (id) => document.getElementById(id);
let renderedCues = [],
  activeCueIndex = -1,
  sourceCueRender = null;
const state = {
  items: [],
  selected: null,
  epoch: 0,
  text: "",
  revision: "",
  editing: false,
  annotationEditingId: "",
  annotationEditingAnchor: {},
  annotationQuote: "",
  annotationQuoteReanchored: false,
  input: "url",
  busy: false,
  refreshing: false,
  cards: [],
  key: "",
  model: {},
  health: {},
};
const presets = {
  deepseek: ["https://api.deepseek.com", "deepseek-flash"],
  kimi: ["https://api.moonshot.cn/v1", "moonshot-v1-8k"],
  openai: ["https://api.openai.com/v1", ""],
  local: ["http://127.0.0.1:1234/v1", ""],
  custom: ["", ""],
};
try {
  const savedModel = localStorage.getItem("learnnote.desk.model");
  state.model = JSON.parse(savedModel || "{}");
  if (!savedModel) {
    const legacy = JSON.parse(
      localStorage.getItem("learnnote_model_settings") || "{}",
    );
    if (legacy.transcriber)
      state.legacyProcessing = {
        transcriber: legacy.transcriber,
        whisper_model: legacy.whisper_model || "small",
        local_ocr: Boolean(legacy.local_ocr),
      };
    if (legacy.llm_base_url) {
      state.model = {
        provider: legacy.llm_provider || "custom",
        base_url: legacy.llm_base_url,
        model: legacy.llm_model || "",
      };
      localStorage.setItem("learnnote.desk.model", JSON.stringify(state.model));
    }
  }
  document.body.classList.toggle(
    "dark",
    localStorage.getItem("learnnote.desk.theme") === "dark",
  );
} catch {}
let noticeTimer;
function notice(message) {
  $("notice").textContent = message;
  $("notice").hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => ($("notice").hidden = true), 6000);
}
function failure(error) {
  notice(error.message || String(error));
}
const syncStatus = document.createElement("button");
syncStatus.id = "connectionStatus";
syncStatus.type = "button";
syncStatus.className = "muted";
syncStatus.hidden = true;
syncStatus.textContent = "同步中断 · 重试";
syncStatus.title = "已显示内容和正在编辑的文字会保留，点击重新连接本机服务";
document.querySelector(".toolbar").append(syncStatus);
syncStatus.onclick = async () => {
  syncStatus.disabled = true;
  state.lastHealthAt = 0;
  try {
    await refresh();
  } catch {
    notice(
      "暂时无法同步。已显示内容和输入仍保留，请确认 LearnNote App 正在运行。",
    );
  } finally {
    syncStatus.disabled = false;
  }
};
function guard() {
  const dirty =
    (state.editing && $("noteText").value !== state.text) ||
    $("annotationText").value.trim();
  return !dirty || confirm("还有未保存的修改或补充。放弃并离开？");
}
function options() {
  const mode = $("createDialog").open
    ? document.querySelector('[name="contentMode"]:checked')?.value || "text"
    : "auto";
  if (
    mode !== "subtitles" &&
    state.model.base_url &&
    !state.key &&
    !state.model.use_saved_connection &&
    state.model.base_url !== state.health.default_llm_base_url &&
    !/^http:\/\/(127\.0\.0\.1|localhost)(:|\/)/.test(state.model.base_url)
  )
    throw new Error("请在设置中填写当前模型服务的 Key，再开始整理。");
  return {
    ...state.processing,
    content_mode: mode,
    use_saved_connection: Boolean(state.model.use_saved_connection),
    summary_depth: $("depth").value,
    generate_questions: Boolean($("generateQuestions")?.checked),
    note_style:
      ($("createDialog").open ? $("taskStyle")?.value : "") ||
      state.processing?.note_style ||
      "study",
    note_template:
      $("taskTemplate")?.value || state.processing?.note_template || "standard",
    visual_understanding:
      mode === "visual" || (mode === "auto" && $("vision").checked),
    local_ocr:
      (mode === "visual" || mode === "auto") && Boolean($("localOcr")?.checked),
    ...(state.model.base_url
      ? { llm_base_url: state.model.base_url, llm_model: state.model.model }
      : {}),
    ...(state.key ? { llm_api_key: state.key } : {}),
  };
}
function updateContentMode() {
  const mode =
    document.querySelector('[name="contentMode"]:checked')?.value || "text";
  $("vision").checked = mode === "visual";
  $("vision").disabled = true;
  $("vision").closest("label").hidden = true;
  if ($("localOcr")) $("localOcr").disabled = mode !== "visual";
  const model =
    state.model.model || state.health.default_llm_model || "尚未配置";
  $("contentModeExplanation").textContent =
    mode === "subtitles"
      ? "不生成 AI 总结。没有可用字幕时会停下来，不会自动改用语音转写。"
      : mode === "visual"
        ? `视觉理解：已启用 · 当前模型：${model}。画面和必要的字幕会发送给该模型。`
        : `视觉理解：关闭 · 文字模型：${model}。本地转写只在没有可用字幕时进行。`;
  $("createSubmit").textContent =
    mode === "subtitles" ? "提取字幕" : "生成笔记";
}
for (const choice of document.querySelectorAll('[name="contentMode"]'))
  choice.addEventListener("change", updateContentMode);
$("createDialog").addEventListener("toggle", () => {
  if ($("createDialog").open) {
    updateContentMode();
    updateCreateInputPresentation();
  }
});
function sourcePath(s = state.selected) {
  return `/api/tasks/editions/${s.kind}/${encodeURIComponent(s.id)}`;
}
function drawList() {
  const query = $("search").value.trim().toLowerCase();
  const rows = state.items
    .filter((item) => item.title.toLowerCase().includes(query))
    .sort((a, b) => {
      const pin = (item) =>
        state.pinned?.has(item.kind + ":" + item.id) ? 1 : 0;
      if (pin(a) !== pin(b)) return pin(b) - pin(a);
      if (state.listSort === "title")
        return a.title.localeCompare(b.title, "zh-CN", { numeric: true });
      if (state.listSort === "active") {
        const active = (item) =>
          ["queued", "running", "cancelling"].includes(item.status) ? 1 : 0;
        if (active(a) !== active(b)) return active(b) - active(a);
      }
      return (b.updated_at || b.created_at || "").localeCompare(
        a.updated_at || a.created_at || "",
      );
    });
  if ($("libraryVisibleCount"))
    $("libraryVisibleCount").textContent = rows.length + " 项";
  $("notes").innerHTML = rows.length
    ? rows
        .map(
          (item) =>
            `<div class="library-row"><button data-id="${esc(item.id)}" data-kind="${item.kind}" aria-current="${state.selected?.id === item.id && state.selected?.kind === item.kind}"><strong>${esc(item.title || "未命名笔记")}</strong><small>${item.kind === "material" ? "资料原文" : statusLabel(item)}${item.updated_at ? " · " + esc(item.updated_at.slice(0, 10)) : ""}</small></button><button class="pin-note" data-pin="${item.kind}:${esc(item.id)}" aria-label="${state.pinned?.has(item.kind + ":" + item.id) ? "取消置顶" : "置顶笔记"}" aria-pressed="${Boolean(state.pinned?.has(item.kind + ":" + item.id))}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M9 3h6l-1 6 3 3v1H7v-1l3-3zM12 13v8"/></svg></button></div>`,
        )
        .join("")
    : `<p class="muted" style="padding:12px">${query ? "没有匹配的笔记" : "添加内容后，笔记会出现在这里。"}</p>`;
}
function showHome({ remember = true, check = true } = {}) {
  if (check && !guard()) return;
  state.navigation ||= [];
  if (remember && state.selected)
    state.navigation.push({ kind: state.selected.kind, id: state.selected.id });
  state.selected = null;
  state.epoch++;
  state.editing = false;
  $("annotationText").value = "";
  closeSource();
  $("reading").hidden = true;
  $("welcome").hidden = false;
  $("noteActions").hidden = true;
  $("breadcrumb").textContent = "我的学习空间";
  history.replaceState(null, "", location.pathname);
  drawList();
  window.dispatchEvent(
    new CustomEvent("learnnote:selection", { detail: null }),
  );
  window.dispatchEvent(new Event("learnnote:navigation"));
}
async function navigateBack() {
  if (!guard()) return;
  const previous = (state.navigation || []).pop();
  if (previous) {
    const item = state.items.find(
      (i) => i.kind === previous.kind && i.id === previous.id,
    );
    if (item) await openItem(item, { remember: false, check: false });
    else showHome({ remember: false, check: false });
  } else showHome({ remember: false, check: false });
  window.dispatchEvent(new Event("learnnote:navigation"));
}
function statusLabel(task) {
  if (task.summary_source === "subtitle-extract") return "字幕已提取";
  if (task.summary_source === "local-template") return "字幕已保留 · 待总结";
  return task.awaiting_confirmation
    ? "等待确认"
    : {
        success: "已完成",
        failed: "需要处理",
        cancelled: "已取消",
        queued: "排队中",
        running: "正在整理",
        cancelling: "正在取消",
      }[task.status] || "正在整理";
}
function refresh() {
  if (!state.refreshPromise)
    state.refreshPromise = refreshLibrary().finally(() => {
      state.refreshPromise = null;
    });
  return state.refreshPromise;
}
async function refreshLibrary() {
  if (state.refreshing) return;
  state.refreshing = true;
  try {
    const [tasks, materials, health] = await Promise.all([
      api("/api/tasks"),
      api("/api/library/materials?limit=1000"),
      Date.now() - (state.lastHealthAt || 0) > 15000
        ? api("/health")
        : Promise.resolve(null),
    ]);
    if (health) {
      state.health = health;
      state.lastHealthAt = Date.now();
    }
    state.connectionError = false;
    syncStatus.hidden = true;
    const previousStatuses = new Map(
      state.items.map((item) => [item.id, item.status]),
    );
    state.items = [
      ...tasks.tasks.map((t) => ({ ...t, kind: "task" })),
      ...materials.materials
        .filter((m) => !m.linked_task_id)
        .map((m) => ({ ...m, kind: "material", id: m.material_id })),
    ].sort((a, b) =>
      (b.updated_at || b.created_at || "").localeCompare(
        a.updated_at || a.created_at || "",
      ),
    );
    syncTaskEventStreams(state.items);
    drawList();
    window.dispatchEvent(new CustomEvent("learnnote:library"));
    const selected =
      state.selected &&
      state.items.find(
        (i) => i.kind === state.selected.kind && i.id === state.selected.id,
      );
    if (selected) {
      const changed = selected.updated_at !== state.selected.updated_at;
      state.selected = selected;
      renderStatus();
      if (changed && !state.editing) {
        await loadEdition(state.epoch);
      }
    }
    const completed = state.items.filter(
      (item) =>
        item.kind === "task" &&
        item.status === "success" &&
        previousStatuses.has(item.id) &&
        previousStatuses.get(item.id) !== "success",
    );
    if (
      state.reading?.notify &&
      window.Notification &&
      Notification.permission === "granted"
    )
      for (const item of completed)
        new Notification("LearnNote · 笔记已完成", { body: item.title });
    if (
      completed.length &&
      state.reading?.autoOpen &&
      !state.editing &&
      !document.querySelector("dialog[open]")
    )
      await openItem(completed[0]);
  } catch (error) {
    state.connectionError = true;
    syncStatus.hidden = false;
    window.dispatchEvent(new CustomEvent("learnnote:library"));
    throw error;
  } finally {
    state.refreshing = false;
  }
}
async function openItem(item, { remember = true, check = true } = {}) {
  if (check && !guard()) return;
  state.navigation ||= [];
  if (
    remember &&
    (!state.selected ||
      state.selected.id !== item.id ||
      state.selected.kind !== item.kind)
  ) {
    state.navigation.push(
      state.selected
        ? { kind: state.selected.kind, id: state.selected.id }
        : null,
    );
    state.navigation = state.navigation.slice(-30);
  }
  window.dispatchEvent(new Event("learnnote:navigation"));
  state.editing = false;
  $("editor").hidden = true;
  $("document").hidden = false;
  state.selected = item;
  api("/api/study/activity", {
    method: "POST",
    body: JSON.stringify({ kind: "reading", source_id: item.kind + ":" + item.id }),
  }).catch(() => {});
  window.dispatchEvent(
    new CustomEvent("learnnote:selection", { detail: item }),
  );
  const epoch = ++state.epoch;
  $("welcome").hidden = true;
  $("reading").hidden = false;
  $("noteActions").hidden = false;
  $("breadcrumb").textContent = item.title;
  $("regenerate").hidden = item.kind !== "task" || item.status !== "success";
  $("document").innerHTML = '<p class="muted">正在打开…</p>';
  $("annotationList").replaceChildren();
  $("annotationText").value = "";
  state.annotationEditingId = "";
  state.annotationEditingAnchor = {};
  state.annotationQuote = "";
  state.annotationQuoteReanchored = false;
  $("annotationQuote").textContent = "";
  $("cancelAnnotationEdit").hidden = true;
  closeSource();
  document.body.classList.remove("menu-open");
  $("menu").setAttribute("aria-expanded", "false");
  history.replaceState(
    null,
    "",
    `#${item.kind}/${encodeURIComponent(item.id)}`,
  );
  drawList();
  renderStatus();
  await Promise.all([loadEdition(epoch), loadAnnotations(epoch)]);
  if (
    epoch === state.epoch &&
    item.kind === "task" &&
    (item.media_path || item.source_media_path)
  )
    await openSource();
}
async function loadEdition(epoch) {
  const selected = state.selected;
  const edition = await api(sourcePath(selected));
  if (epoch !== state.epoch || state.editing) return;
  state.text = edition.text;
  state.revision = edition.revision;
  state.edition = edition;
  renderNote();
}
function renderNote() {
  // Keep the edition hash alongside the rendered document so annotations and
  // source repair can distinguish a stable anchor from an outdated selection.
  $("document").dataset.sourceRevision = state.revision || "";
  $("annotations").dataset.sourceRevision = state.revision || "";
  LearnNoteMarkdown.configure({
    safeNoteMediaUrl: (value) =>
      state.selected?.kind === "task"
        ? taskAsset(value, state.selected.id)
        : "",
  });
  const excerptOnly =
    state.selected.summary_source === "local-template" &&
    !state.edition?.edited;
  const heading =
    state.text.trim().startsWith("# ") && !excerptOnly
      ? ""
      : `<h1>${esc(state.selected.title)}</h1>`;
  const decode = state.selected.kind === "material" ? state.selected.metadata || {} : {};
  const decodeSource = ({
    "bom": "BOM",
    "declared-charset": "文件声明字符集",
    "strict-utf8": "严格 UTF-8",
    "charset-normalizer": "自动识别",
    "fallback": "编码候选",
    "user-selected": "手动选择",
    "pypdf": "PDF 文本提取",
  })[decode.encoding_source] || "未知来源";
  const decodeConfidence = ({ high: "高", medium: "中", low: "低", user_selected: "手动指定", not_applicable: "不适用" })[decode.encoding_confidence] || "未知";
  const rawStatus = state.selected.stored_locally ? "原始文件已保留。" : "原始文件当前不可用。";
  const decodeNotice = decode.encoding
    ? `<p class="encoding-provenance-note" role="status">原文解码：${esc(decode.encoding)} · ${esc(decodeSource)} · 选择依据${esc(decodeConfidence)}。${decode.encoding_confidence === "low" ? "自动识别把握较低，请核对原文。" : rawStatus}</p>`
    : "";
  $("document").innerHTML =
    decodeNotice +
    (state.selected.kind === "task" && /llm/i.test(state.selected.summary_source || "")
      ? '<p class="muted" role="status">AI 草稿：生成完成不代表逐条事实已验证。请结合字幕与原视频核对数字、名称和推断。<button id="reviewNoteSources" type="button">查看字幕与原视频</button></p>'
      : "") +
    heading +
    (state.text.trim()
      ? excerptOnly
        ? `<p class="muted">这里暂时保留的是字幕摘录。上方可以重新生成总结，原始字幕也可随时核对。</p><details class="transcript-draft"><summary>查看已保留的字幕摘录</summary>${LearnNoteMarkdown.markdownToHtml(state.text.replace(/^# .+\n/, ""))}</details>`
        : LearnNoteMarkdown.markdownToHtml(state.text)
      : '<p class="muted">笔记准备好后会显示在这里，你可以先查看处理进度。</p>');
  $("reviewNoteSources")?.addEventListener("click", () => openSource().catch(failure));
  if (state.selected.kind === "task")
    for (const code of $("document").querySelectorAll("code")) {
      if (code.closest("pre")) continue;
      const match = code.textContent.match(/^(\d{1,3}):(\d{2})(?::(\d{2}))?$/);
      if (!match) continue;
      const seconds = match[3]
        ? Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3])
        : Number(match[1]) * 60 + Number(match[2]);
      const button = document.createElement("button");
      button.className = "time-link";
      button.textContent = code.textContent;
      button.onclick = () => openSource(seconds).catch(failure);
      code.replaceWith(button);
    }
  if (state.selected.kind === "task") {
    const walker = document.createTreeWalker(
      $("document"),
      NodeFilter.SHOW_TEXT,
    );
    const textNodes = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (
        !node.parentElement.closest("pre,code,a,button,script,style") &&
        timestampRanges(node.textContent).length
      )
        textNodes.push(node);
    }
    for (const node of textNodes) {
      const fragment = document.createDocumentFragment();
      let offset = 0;
      for (const range of timestampRanges(node.textContent)) {
        fragment.append(
          document.createTextNode(node.textContent.slice(offset, range.index)),
        );
        const button = document.createElement("button");
        button.type = "button";
        button.className = "time-link";
        button.textContent = range.label;
        button.setAttribute("aria-label", `查看原文 ${range.label}`);
        button.onclick = () => openSource(range.start).catch(failure);
        fragment.append(button);
        offset = range.index + range.label.length;
      }
      fragment.append(document.createTextNode(node.textContent.slice(offset)));
      node.replaceWith(fragment);
    }
  }
  window.dispatchEvent(new Event("learnnote:document"));
}
const taskEvents = new Map();
const taskEventHub = createTaskEventHub({
  connect: url => new EventSource(url),
  onUpdate: () => refresh(),
  onInvalidate: taskId => taskEvents.delete(taskId),
});
function syncTaskEventStreams(items = state.items) {
  if (typeof EventSource !== "function") return;
  taskEventHub.sync(items, document.hidden);
}
window.addEventListener("visibilitychange", () => {
  if (document.hidden) taskEventHub.disconnect();
  else syncTaskEventStreams();
});
window.addEventListener("pagehide", () => {
  taskEventHub.disconnect();
});
async function loadTaskEvents(task) {
  const cached = taskEvents.get(task.id);
  if (
    cached?.loading ||
    (cached?.stamp === task.updated_at && Date.now() - cached.checked < 5000)
  )
    return;
  const record = {
    ...cached,
    loading: true,
    stamp: task.updated_at,
    checked: Date.now(),
  };
  taskEvents.set(task.id, record);
  try {
    const value = await api(`/api/tasks/${task.id}/events?limit=500`);
    record.events = value.events || [];
  } catch {
    record.events ||= [];
  } finally {
    record.loading = false;
  }
  if (state.selected?.id === task.id) renderStatus(false);
}
function renderStatus(reload = true) {
  const t = state.selected;
  $("regenerate").hidden = t.kind !== "task" || t.status !== "success";
  const panel = $("taskStatus");
  panel.hidden = t.kind !== "task";
  if (panel.hidden) return;
  if (reload) loadTaskEvents(t);
  const stopped = ["failed", "cancelled"].includes(t.status);
  const needsSummary = Boolean(
    t.transcript_path &&
      (["summary_unavailable", "note_quality_failed"].includes(t.error_code) ||
        t.summary_source === "local-template"),
  );
  const queueDetail =
    t.status === "queued" && t.queue?.position
      ? " · 队列第 " + t.queue.position + " 位 · " + (t.queue.queued_count || 0) + " 个等待"
      : "";
  const canResume =
    t.resume_available ?? Boolean(t.media_path || t.source_media_path);
  const busy = state.taskAction?.id === t.id;
  const action = t.awaiting_confirmation
    ? '<button class="primary" data-task-action="start">开始读取并整理</button>'
    : needsSummary
      ? '<button class="primary" data-task-action="retry-summary">重新生成总结</button>'
      : stopped
        ? canResume
          ? '<button data-task-action="resume">继续处理已有文件</button>'
          : '<button data-task-action="new">重新添加来源</button>'
        : ["success", "cancelling"].includes(t.status)
          ? ""
          : '<button data-task-action="cancel">停止处理</button>';
  const title = (needsSummary ? "字幕已保留 · 总结尚未完成" : statusLabel(t)) + queueDetail;
  const raw =
    t.message && !["success"].includes(t.status)
      ? `<details class="task-detail"><summary>当前步骤详情</summary><p>${esc(t.message)}</p></details>`
      : "";
  const priorProgress = panel.querySelector("[data-task-progress]");
  const progressExpanded =
    priorProgress?.dataset.taskProgress === t.id
      ? priorProgress.open
      : t.status !== "success";
  panel.innerHTML = `<div class="task-status-heading"><strong>${esc(title)}</strong><button data-task-action="diagnostics">查看处理记录</button></div><p>${esc(taskExplanation(t))}</p>${timelineHtml(t, taskEvents.get(t.id)?.events || [], progressExpanded)}${t.awaiting_confirmation ? `<p class="task-plan">${t.options?.content_mode === "subtitles" ? "仅提取字幕 · 不调用模型" : `${t.options?.visual_understanding ? "图文笔记 · 视觉理解已启用" : "文字笔记 · 视觉理解关闭"} · ${esc(state.model.model || state.health.default_llm_model || "尚未配置模型")}`}</p>` : ""}<div class="task-status-actions">${action}</div>${raw}`;
  if (t.claim_evidence?.path) {
    const details = document.createElement("details");
    details.className = "claim-evidence-details";
    const summary = document.createElement("summary");
    const quality = t.claim_evidence.quality || {};
    const locatedOnlyCount = Number(quality.located_only_count || 0);
    const inferenceCount = Number(quality.inference_count || 0);
    const pendingReviewCount = Number(quality.pending_review_count || 0);
    summary.textContent = `逐条来源映射 · ${Number(quality.claim_count || 0)} 条 · 直接支持 ${Number(quality.direct_count || 0)} · 仅定位 ${locatedOnlyCount} · 推断 ${inferenceCount} · 待核对 ${pendingReviewCount}`;
    if (locatedOnlyCount || inferenceCount || pendingReviewCount || quality.unsupported_count) {
      const warning = document.createElement("p");
      warning.className = "muted";
      warning.textContent = "逐条状态中的“仅定位”“推断”“待核对”均需要人工检查。时间戳只用于定位，不代表结论已经验证。";
      panel.append(warning);
    }
    details.append(summary);
    const body = document.createElement("div");
    body.className = "claim-evidence-body";
    body.textContent = "展开后读取本地映射；这里的支持表示可定位来源，不代表课程事实已经被外部验证。";
    details.append(body);
    details.addEventListener("toggle", async () => {
      if (!details.open || details.dataset.loaded) return;
      details.dataset.loaded = "true";
      try {
        const mapped = await api("/api/tasks/" + t.id + "/claims");
        const list = document.createElement("ol");
        for (const claim of mapped.claims || []) {
          const item = document.createElement("li");
          const text = document.createElement("span");
          const verificationLabel = ({
            "direct": "直接支持",
            "located_only": "仅定位",
            "inference": "推断",
            "pending_review": "待核对",
          })[claim.verification] || "待核对";
          const sourceLabel = ({
            "transcript": "字幕",
            "visual": "画面",
            "document": "文档",
          })[claim.claim_type] || "";
          text.textContent = `${verificationLabel}${sourceLabel ? ` · ${sourceLabel}` : ""} · ${claim.text}`;
          item.append(text);
          const evidence = (mapped.evidence || []).filter((candidate) => [...(claim.evidence_ids || []), ...(claim.candidate_evidence_ids || [])].includes(candidate.evidence_id));
          for (const candidate of evidence.slice(0, 3)) {
            if (candidate.kind === "document" && candidate.material_id) {
              const locate = document.createElement("button");
              locate.type = "button";
              locate.textContent = `打开文档 ${candidate.locator || "出处"}`;
              locate.onclick = async () => {
                const material = state.items.find((entry) => entry.kind === "material" && entry.id === candidate.material_id);
                if (!material) {
                  notice("这份文档不在当前资料库中，无法打开出处。");
                  return;
                }
                await openItem(material).catch(failure);
                const locator = String(candidate.locator || "");
                const page = /page\s+(\d+)/i.exec(locator)?.[1];
                const excerpt = String(candidate.text || "").replace(/\s+/g, " ").trim().slice(0, 80);
                const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
                const blocks = Array.from(document.querySelectorAll("#document h1, #document h2, #document h3, #document p, #document li, #document blockquote, #document pre, #document td, #document th"));
                const target = (page && blocks.find((block) => normalize(block.textContent).includes(`[第 ${page} 页]`))) ||
                  (excerpt.length >= 16 && blocks.find((block) => normalize(block.textContent).includes(excerpt)));
                document.querySelectorAll("#document .source-evidence-target").forEach((block) => block.classList.remove("source-evidence-target"));
                if (target) {
                  target.classList.add("source-evidence-target");
                  target.scrollIntoView({ block: "center", behavior: "instant" });
                } else {
                  notice(`已打开文档，但无法精确高亮 ${locator || "该出处"}。`);
                }
              };
              item.append(locate);
              continue;
            }
            const match = String(candidate.locator || "").match(/^([0-9.]+)-/);
            if (!match || t.kind !== "task") continue;
            const locate = document.createElement("button");
            locate.type = "button";
            locate.textContent = "定位 " + candidate.locator;
            locate.onclick = () => openSource(Number(match[1]), t).catch(failure);
            item.append(locate);
          }
          list.append(item);
        }
        body.replaceChildren(list);
      } catch (error) {
        body.textContent = error.message || "逐条来源暂时无法读取。";
      }
    });
    panel.append(details);
  }
  panel.dataset.status = needsSummary ? "needs-summary" : t.status;
  for (const button of panel.querySelectorAll("button"))
    button.disabled = Boolean(busy);
}
async function loadAnnotations(epoch) {
  const s = state.selected;
  const value = await api(`/api/personal/${s.kind}/${s.id}`);
  if (epoch !== state.epoch) return;
  $("annotationList").innerHTML = value.annotations
    .map((a) => `<div class="annotation${a.anchor_status?.stale ? " annotation-stale" : ""}">${a.quote ? `<blockquote>${esc(a.quote)}</blockquote>` : ""}<span>${esc(a.text)}</span>${a.anchor_status?.stale ? `<small>${a.anchor_status.repairable ? "原文版本已变化；重新选择当前正文以修复出处。" : "原文版本已变化；没有可恢复的引用片段。"}</small>` : ""}<button type="button" data-annotation-edit="${esc(a.id)}">${a.anchor_status?.stale ? "修复出处" : "编辑"}</button><button type="button" class="danger" data-annotation-delete="${esc(a.id)}">删除</button></div>`)
    .join("");
  for (const button of $("annotationList").querySelectorAll("[data-annotation-edit]")) button.onclick = () => {
    const item = value.annotations.find((annotation) => annotation.id === button.dataset.annotationEdit);
    if (!item) return;
    state.annotationEditingId = item.id;
    state.annotationEditingAnchor = item.anchor && typeof item.anchor === "object" ? item.anchor : {};
    state.annotationQuote = String(item.quote || "");
    state.annotationQuoteReanchored = false;
    $("annotationText").value = item.text;
    $("annotationQuote").textContent = state.annotationQuote ? `引用：${state.annotationQuote}` : "尚未关联原文。";
    $("saveAnnotation").textContent = item.anchor_status?.stale ? "修复出处并保存" : "保存修改";
    $("cancelAnnotationEdit").hidden = false;
    $("annotationText").focus();
  };
  for (const button of $("annotationList").querySelectorAll("[data-annotation-delete]")) button.onclick = async () => {
    if (!confirm("删除这条个人补充？")) return;
    try {
      await api(`/api/personal/${state.selected.kind}/${state.selected.id}/${encodeURIComponent(button.dataset.annotationDelete)}`, { method: "DELETE" });
      await loadAnnotations(epoch);
    } catch (error) { failure(error); }
  };
}
let sourceRequest = 0;
function closeSource() {
  sourceRequest++;
  $("sourcePanel").hidden = true;
  document.body.classList.remove("source-open");
  $("player").pause();
  $("onlinePlayer")?.removeAttribute("src");
  sourceCueRender = null;
}

async function openInlineSource(seconds, sourceOverride = null, endSeconds = undefined) {
  let source = sourceOverride || state.selected;
  if (!source) return;
  if (!state.selected || source.id !== state.selected.id || source.kind !== state.selected.kind) {
    const item = state.items.find((candidate) => candidate.id === source.id && candidate.kind === source.kind);
    if (!item) {
      notice("引用来源已不在当前资料库，无法可靠定位。");
      return;
    }
    await openItem(item, { remember: true, check: false });
    source = state.selected;
  }
  const view = $("inlineSourceView"), content = $("inlineSourceContent"), meta = $("inlineSourceMeta");
  state.summaryScrollY = window.scrollY;
  view.hidden = false;
  $("document").hidden = true;
  content.replaceChildren();
  meta.textContent = "正在读取原文…";
  try {
    if (source.kind === "material") {
      const data = await api(`/api/library/materials/${encodeURIComponent(source.id)}/content`);
      meta.textContent = `${source.title} · 文档原文`;
      for (const paragraph of String(data.text || "").split(/\n{2,}/).filter(Boolean)) {
        const node = document.createElement("p");
        node.textContent = paragraph;
        content.append(node);
      }
    } else {
      const data = await api(`/api/tasks/${encodeURIComponent(source.id)}/transcript`);
      const cues = (data.segments || []).filter((cue) => String(cue.text || "").trim());
      let matched = false;
      for (const cue of cues) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "inline-cue";
        button.dataset.time = String(Number(cue.start) || 0);
        const time = document.createElement("time");
        time.textContent = timestamp(cue.start);
        button.append(time, document.createTextNode(String(cue.text || "")));
        const rangeEnd = typeof endSeconds === "number" ? endSeconds : seconds;
        if (typeof seconds === "number" && Number(cue.start) <= rangeEnd && Number(cue.end ?? cue.start) >= seconds) {
          button.classList.add("active");
          matched = true;
        }
        button.onclick = () => {
          // Location is independent from playback. The video controls remain
          // available in the source panel when the learner explicitly opens it.
          button.scrollIntoView({ block: "center", behavior: "instant" });
        };
        content.append(button);
      }
      meta.textContent = matched
        ? `${source.title} · 已定位到 ${timestamp(seconds)}${typeof endSeconds === "number" && endSeconds > seconds ? `–${timestamp(endSeconds)}` : ""}`
        : `${source.title} · 没有与引用时间范围精确匹配的字幕段，未猜测高亮位置`;
      if (!cues.length) content.textContent = "暂无可用字幕。";
      content.querySelector(".inline-cue.active")?.scrollIntoView({ block: "center", behavior: "instant" });
    }
    view.scrollIntoView({ block: "start", behavior: "instant" });
  } catch (error) {
    meta.textContent = error.message || "原文暂时无法读取。";
  }
}

$("backToSummary").onclick = () => {
  $("inlineSourceView").hidden = true;
  $("document").hidden = false;
  window.scrollTo({ top: Number(state.summaryScrollY || 0), behavior: "instant" });
};

async function openSource(seconds, sourceOverride = null) {
  const s = sourceOverride || state.selected;
  if (!s) return;
  const panel = $("sourcePanel"),
    player = $("player"),
    transcript = $("sourceTranscript"),
    sourceKey = `${s.kind}:${s.id}:${s.updated_at || ""}`;
  panel.hidden = false;
  document.body.classList.add("source-open");
  const seek = () => {
    const remote = $("onlinePlayer");
    if (remote && !remote.hidden && (seconds !== undefined || !remote.getAttribute("src"))) {
      remote.src = sourceVideoEmbed(s.page_url, Number(seconds || 0), Number(s.learning_range?.start || 0));
    }
    if (seconds === undefined) return;
    if (sourceCueRender) sourceCueRender(seconds);
    if (transcript) transcript.open = true;
    if (!player.hidden) {
      player.currentTime = seconds;
    }
    if (renderedCues.length) {
      const cue =
        renderedCues.findLast((item) => Number(item.dataset.time) <= seconds) ||
        renderedCues[0];
      renderedCues.forEach((item) =>
        item.classList.toggle("active", item === cue),
      );
      const content = $("sourceContent"),
        box = content.getBoundingClientRect();
      content.scrollTop += cue.getBoundingClientRect().top - box.top - 8;
    }
  };
  if (
    panel.dataset.sourceKey === sourceKey &&
    panel.dataset.contentMode === "transcript"
  ) {
    seek();
    panel.scrollIntoView({ block: "nearest", behavior: "instant" });
    return;
  }
  const request = ++sourceRequest;
  delete panel.dataset.sourceKey;
  panel.dataset.contentMode = "loading";
  renderedCues = [];
  activeCueIndex = -1;
  const epoch = state.epoch;
  $("sourceContent").textContent = "正在打开原始来源…";
  if (transcript) transcript.open = true;
  const hasMedia =
    s.kind === "task" && Boolean(s.media_path || s.source_media_path);
  let online = $("onlinePlayer");
  if (!online) {
    online = document.createElement("iframe"); online.id = "onlinePlayer";
    online.title = "原视频 · Bilibili 在线播放";
    online.allow = "fullscreen; picture-in-picture";
    online.referrerPolicy = "strict-origin-when-cross-origin";
    player.after(online);
  }
  const embedUrl = !hasMedia && s.kind === "task" ? sourceVideoEmbed(s.page_url, Number(seconds || 0), Number(s.learning_range?.start || 0)) : "";
  online.hidden = !embedUrl;
  if (embedUrl) online.src = embedUrl;
  else online.removeAttribute("src");
  player.hidden = !hasMedia;
  if (hasMedia) {
    const url = `/api/tasks/${s.id}/media`;
    if (player.getAttribute("src") !== url) player.src = url;
  } else if (player.hasAttribute("src")) {
    player.removeAttribute("src");
    player.load();
  }
  try {
    if (s.kind === "material") {
      const data = await api(`/api/library/materials/${s.id}/content`);
      if (epoch !== state.epoch || request !== sourceRequest) return;
      $("sourceContent").textContent = data.text;
      panel.dataset.sourceKey = sourceKey;
      panel.dataset.contentMode = "transcript";
      transcript.querySelector("summary").textContent = "查看资料原文";
      return;
    }
    const data = await api(`/api/tasks/${s.id}/transcript`);
    if (epoch !== state.epoch || request !== sourceRequest) return;
    const cues = data.segments || [];
    sourceCueRender = null;
    if (cues.length > 160) {
      const content = $("sourceContent");
      content.innerHTML = s.page_url
        ? '<a href="' + esc(/^https?:/.test(s.page_url) ? s.page_url : "#") + '" target="_blank" rel="noreferrer">打开原网页 ↗</a>'
        : "";
      const viewport = document.createElement("div");
      viewport.className = "virtual-cues";
      content.append(viewport);
      sourceCueRender = (focusSeconds) => {
        if (typeof focusSeconds === "number") {
          const focusIndex = cues.findLastIndex((cue) => Number(cue.start) <= focusSeconds);
          if (focusIndex >= 0) content.scrollTop = Math.max(0, focusIndex * 72 - 80);
        }
        const estimatedHeight = 72;
        const visibleStart = Math.max(0, Math.floor(content.scrollTop / estimatedHeight) - 8);
        const visibleEnd = Math.min(cues.length, visibleStart + Math.ceil(Math.max(content.clientHeight, 280) / estimatedHeight) + 16);
        viewport.style.paddingTop = visibleStart * estimatedHeight + "px";
        viewport.style.paddingBottom = Math.max(0, cues.length - visibleEnd) * estimatedHeight + "px";
        viewport.replaceChildren(...cues.slice(visibleStart, visibleEnd).map((cue, index) => {
          const button = document.createElement("button");
          button.className = "cue";
          button.dataset.time = String(Number(cue.start) || 0);
          button.setAttribute("aria-setsize", String(cues.length));
          button.setAttribute("aria-posinset", String(visibleStart + index + 1));
          const time = document.createElement("small");
          time.textContent = timestamp(cue.start);
          button.append(time, document.createTextNode(String(cue.text || "")));
          return button;
        }));
        renderedCues = [...viewport.querySelectorAll(".cue")];
      };
      content.addEventListener("scroll", () => sourceCueRender(), { passive: true });
      sourceCueRender();
      panel.dataset.sourceKey = sourceKey;
      panel.dataset.contentMode = "transcript";
      if (transcript) {
        transcript.querySelector("summary").textContent = "查看原始字幕 · " + cues.length + " 段";
        transcript.open = !hasMedia || seconds !== undefined;
      }
      seek();
      panel.scrollIntoView({ block: "nearest", behavior: "instant" });
      return;
    }
    $("sourceContent").innerHTML =
      (s.page_url
        ? `<a href="${esc(/^https?:/.test(s.page_url) ? s.page_url : "#")}" target="_blank" rel="noreferrer">打开原网页 ↗</a>`
        : "") +
      cues
        .map(
          (c) =>
            `<button class="cue" data-time="${Number(c.start) || 0}"><small>${timestamp(c.start)}</small>${esc(c.text)}</button>`,
        )
        .join("");
    renderedCues = [...$("sourceContent").querySelectorAll(".cue")];
    activeCueIndex = -1;
    if (!cues.length)
      $("sourceContent").append(document.createTextNode("暂无可用字幕。"));
    panel.dataset.sourceKey = sourceKey;
    panel.dataset.contentMode = "transcript";
    if (transcript) {
      transcript.querySelector("summary").textContent =
        `查看原始字幕${cues.length ? " · " + cues.length + " 段" : ""}`;
      transcript.open = !hasMedia || seconds !== undefined;
    }
    seek();
    panel.scrollIntoView({ block: "nearest", behavior: "instant" });
  } catch (error) {
    if (epoch === state.epoch && request === sourceRequest)
      $("sourceContent").textContent = error.message;
  }
}
$("player").addEventListener("timeupdate", () => {
  const time = $("player").currentTime;
  const index = renderedCues.findLastIndex(
    (c) => Number(c.dataset.time) <= time,
  );
  if (index === activeCueIndex) return;
  renderedCues[activeCueIndex]?.classList.remove("active");
  renderedCues[index]?.classList.add("active");
  activeCueIndex = index;
  const cue = renderedCues[index];
  if (cue && $("followTranscript")?.checked && cue.getClientRects().length) {
    const bounds = cue.getBoundingClientRect(),
      content = $("sourceContent"),
      panel = content.getBoundingClientRect();
    if (bounds.bottom > panel.bottom - 8 || bounds.top < panel.top + 8)
      content.scrollTop += bounds.top - panel.top - 8;
  }
});
$("player").addEventListener("error", () => {
  if (!$("sourcePanel").hidden)
    notice("本地视频暂不可播放；仍可阅读字幕或打开原网页。");
});
$("sourceContent").onclick = (e) => {
  const cue = e.target.closest("[data-time]");
  if (cue && !$("player").hidden) {
    $("player").currentTime = Number(cue.dataset.time);
  } else if (cue) {
    openSource(Number(cue.dataset.time));
  }
};
$("notes").onclick = (e) => {
  const row = e.target.closest("[data-id]");
  if (row)
    openItem(
      state.items.find(
        (i) => i.id === row.dataset.id && i.kind === row.dataset.kind,
      ),
    ).catch(failure);
};
$("search").oninput = drawList;
$("refresh").onclick = () => {
  state.lastHealthAt = 0;
  refresh().catch(failure);
};
$("source").onclick = () =>
  $("sourcePanel").hidden ? openSource().catch(failure) : closeSource();
$("closeSource").onclick = closeSource;
$("edit").onclick = () => {
  state.editing = true;
  $("noteText").value = state.text;
  $("document").hidden = true;
  $("editor").hidden = false;
  $("noteText").focus();
};
$("discard").onclick = () => {
  if (!guard()) return;
  state.editing = false;
  $("editor").hidden = true;
  $("document").hidden = false;
};
$("save").onclick = async () => {
  const s = state.selected,
    epoch = state.epoch;
  $("save").disabled = true;
  try {
    const result = await api(sourcePath(s), {
      method: "PUT",
      body: JSON.stringify({
        text: $("noteText").value,
        revision: state.revision,
      }),
    });
    if (epoch !== state.epoch) return;
    state.text = result.text;
    state.revision = result.revision;
    state.editing = false;
    renderNote();
    $("editor").hidden = true;
    $("document").hidden = false;
    notice("修改已保存，原始生成稿仍保留。");
  } catch (error) {
    $("saveStatus").textContent = error.message;
  } finally {
    $("save").disabled = false;
  }
};
$("export").onclick = () => {
  const blob = new Blob([state.editing ? $("noteText").value : state.text], {
    type: "text/markdown;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download =
    (state.selected.title || "笔记").replace(/[<>:"/\\|?*]/g, "_") + ".md";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
$("annotationForm").onsubmit = async (e) => {
  e.preventDefault();
  const epoch = state.epoch,
    s = state.selected,
    text = $("annotationText").value;
  const button = e.submitter;
  button.disabled = true;
  try {
    const quote = state.annotationQuote;
    const anchor = state.annotationQuoteReanchored && quote
      ? { source_revision: state.revision, selected_text: quote }
      : state.annotationEditingAnchor;
    await api(`/api/personal/${s.kind}/${s.id}`, {
      method: "POST",
      body: JSON.stringify({
        text,
        quote: quote.slice(0, 1000),
        id: state.annotationEditingId,
        anchor,
      }),
    });
    if (epoch !== state.epoch) return;
    $("annotationText").value = "";
    $("annotationQuote").textContent = "";
    $("saveAnnotation").textContent = "保存补充";
    $("cancelAnnotationEdit").hidden = true;
    state.annotationEditingId = "";
    state.annotationEditingAnchor = {};
    state.annotationQuote = "";
    state.annotationQuoteReanchored = false;
    await loadAnnotations(epoch);
  } catch (error) {
    failure(error);
  } finally {
    button.disabled = false;
  }
};
$("captureAnnotationQuote").onclick = () => {
  const selection = window.getSelection?.();
  if (!selection?.anchorNode || !$("document").contains(selection.anchorNode)) {
    notice("先在笔记正文中选中一段文字，再关联出处。");
    return;
  }
  const quote = String(selection).trim().slice(0, 1000);
  if (!quote) { notice("所选文字为空，请重新选择。"); return; }
  state.annotationQuote = quote;
  state.annotationQuoteReanchored = true;
  $("annotationQuote").textContent = `引用：${quote}`;
};
$("captureAnnotationQuote").onmousedown = (event) => event.preventDefault();
$("cancelAnnotationEdit").onclick = () => {
  state.annotationEditingId = "";
  state.annotationEditingAnchor = {};
  state.annotationQuote = "";
  state.annotationQuoteReanchored = false;
  $("annotationText").value = "";
  $("annotationQuote").textContent = "";
  $("saveAnnotation").textContent = "保存补充";
  $("cancelAnnotationEdit").hidden = true;
};
function create() {
  updateContentMode();
  if (!$("createDialog").open) $("createDialog").showModal();
  window.dispatchEvent(new CustomEvent("learnnote:create"));
}
$("newNote").onclick = create;
$("welcomeNew").onclick = create;
for (const button of document.querySelectorAll("[data-close]"))
  button.onclick = () => button.closest("dialog").close();
function updateCreateInputPresentation() {
  const file = $("file").files?.[0];
  const isDocument =
    state.input === "file" && file && /\.(pdf|md|txt|html?)$/i.test(file.name);
  const hideVideoOptions =
    state.input === "browser" || (state.input === "file" && (!file || isDocument));
  $("contentModeChoices").hidden = hideVideoOptions;
  $("contentModeExplanation").hidden = hideVideoOptions;
  $("generationOptions").hidden = hideVideoOptions;
  const needsFile = state.input === "file" && !file;
  $("createSubmit").disabled = needsFile;
  if (needsFile) {
    $("createSubmit").textContent = "先选择文件";
  } else if (isDocument) {
    $("createSubmit").textContent = "导入并阅读资料";
  } else {
    updateContentMode();
  }
}
$("file").addEventListener("change", updateCreateInputPresentation);
for (const button of document.querySelectorAll("[data-input]"))
  button.onclick = () => {
    state.input = button.dataset.input;
    for (const el of document.querySelectorAll("[data-input]"))
      el.setAttribute("aria-pressed", String(el === button));
    for (const kind of ["url", "file", "browser"])
      $(kind + "Input").hidden = kind !== state.input;
    $("createSubmit").hidden = state.input === "browser";
    updateCreateInputPresentation();
    $("createStatus").textContent = "";
  };
function updateMaterialEncodingChoice() {
  const file = $("file").files?.[0];
  const isMaterial = Boolean(file && /\.(md|markdown|txt|html?)$/i.test(file.name));
  $("materialEncodingChoice").hidden = !isMaterial;
  if (!isMaterial) $("materialEncoding").value = "";
}
$("file").addEventListener("change", updateMaterialEncodingChoice);
$("createForm").onsubmit = async (e) => {
  e.preventDefault();
  if (state.busy) return;
  state.busy = true;
  $("createSubmit").disabled = true;
  $("createStatus").textContent = "正在提交，请稍候…";
  try {
    let result,
      kind = "task";
    if (state.input === "url") {
      if (!$("url").value.trim()) throw new Error("请先粘贴视频地址。");
      result = await api("/api/tasks/from-current-page", {
        method: "POST",
        body: JSON.stringify({
          page_url: $("url").value.trim(),
          options: options(),
        }),
      });
    } else {
      const file = $("file").files[0];
      if (!file) throw new Error("请先选择文件。");
      const data = new FormData();
      data.append("file", file);
      kind = /\.(pdf|md|txt|html?)$/i.test(file.name) ? "material" : "task";
      const requestedEncoding = kind === "material" ? String($("materialEncoding").value || "") : "";
      if (kind === "material") data.append("encoding", requestedEncoding);
      if (kind === "task") data.append("options", JSON.stringify(options()));
      result = await api(
        kind === "task"
          ? "/api/tasks/from-local"
          : "/api/library/materials/import",
        { method: "POST", body: data },
      );
      const metadata = result?.material?.metadata || {};
      if (kind === "material" && result?.material?.deduplicated && requestedEncoding && String(metadata.encoding || "").toLowerCase() !== requestedEncoding.toLowerCase()) {
        throw new Error(`这份资料已经导入，当前版本按 ${metadata.encoding || "未知编码"} 解码；本次没有覆盖原资料。`);
      }
    }
    await refresh();
    const id = result.task_id || result.material?.material_id;
    const item =
      state.items.find((i) => i.id === id && i.kind === kind) ||
      (kind === "material"
        ? { ...result.material, id, kind }
        : { ...result.task, id, kind });
    $("createDialog").close();
    if (item) await openItem(item);
    $("url").value = "";
    $("file").value = "";
    $("materialEncoding").value = "";
    updateMaterialEncodingChoice();
    $("createStatus").textContent = "";
  } catch (error) {
    $("createStatus").textContent = error.message;
  } finally {
    state.busy = false;
    $("createSubmit").disabled = false;
  }
};
$("taskStatus").onclick = async (e) => {
  const button = e.target.closest("[data-task-action]");
  if (!button || state.taskAction) return;
  const selected = state.selected,
    action = button.dataset.taskAction;
  if (action === "diagnostics") {
    await workspaceTools.diagnostics().catch(failure);
    return;
  }
  if (action === "new") {
    $("newNote").click();
    if (selected.page_url) {
      document.querySelector('[data-input="url"]').click();
      $("url").value = selected.page_url;
    }
    return;
  }
  state.taskAction = { id: selected.id, action };
  renderStatus();
  try {
    await api(`/api/tasks/${selected.id}/${action}`, {
      method: "POST",
      body: JSON.stringify(
        action === "cancel"
          ? {}
          : ["resume", "retry-summary"].includes(action)
            ? {
                ...selected.options,
                use_saved_connection: Boolean(state.model.use_saved_connection),
                ...(state.model.base_url
                  ? {
                      llm_base_url: state.model.base_url,
                      llm_model: state.model.model,
                    }
                  : {}),
                ...(state.key ? { llm_api_key: state.key } : {}),
              }
            : options(),
      ),
    });
    await refresh();
  } catch (error) {
    failure(error);
  } finally {
    state.taskAction = null;
    if (state.selected) renderStatus();
  }
};

$("settings").onclick = () => {
  const provider = presets[state.model.provider]
    ? state.model.provider
    : "deepseek";
  $("provider").value = provider;
  $("baseUrl").value = state.model.base_url || presets[provider][0];
  $("model").value = state.model.model || presets[provider][1];
  $("apiKey").value = state.key;
  $("settingsDialog").showModal();
};
$("provider").onchange = () => {
  [$("baseUrl").value, $("model").value] = presets[$("provider").value];
  $("apiKey").value = "";
};
$("testModel").onclick = async () => {
  $("testModel").disabled = true;
  $("settingsStatus").textContent = "正在测试连接…";
  try {
    const result = await api("/api/model/setup/check", {
      method: "POST",
      body: JSON.stringify({
        provider: $("provider").value,
        base_url: $("baseUrl").value,
        model: $("model").value,
        api_key: $("apiKey").value,
        use_saved_connection:
          Boolean(state.model.use_saved_connection) &&
          $("baseUrl").value.trim() === state.model.base_url &&
          !$("apiKey").value.trim(),
        mode: "chat",
      }),
    });
    $("settingsStatus").textContent =
      result.message || (result.ok ? "连接成功" : "连接失败");
  } catch (error) {
    $("settingsStatus").textContent = error.message;
  } finally {
    $("testModel").disabled = false;
  }
};
$("settingsForm").onsubmit = async (e) => {
  e.preventDefault();
  const collect = () => ({
    provider: $("provider").value,
    base_url: $("baseUrl").value.trim().replace(/\/$/, ""),
    model: $("model").value.trim(),
    api_key: $("apiKey").value.trim(),
  });
  const draft = collect();
  const snapshot = JSON.stringify(draft);
  const epoch = (state.modelSaveEpoch = (state.modelSaveEpoch || 0) + 1);
  $("savePreferences").disabled = true;
  $("settingsStatus").textContent = "正在保存模型连接…";
  try {
    const result = await api("/api/model/connection", {
      method: "PUT",
      body: JSON.stringify({
        ...draft,
        use_saved_connection:
          Boolean(state.model.use_saved_connection) &&
          draft.base_url === state.model.base_url &&
          !draft.api_key,
      }),
    });
    if (epoch !== state.modelSaveEpoch) return;
    state.model = result.model;
    state.key = "";
    state.modelConnectionReady = Boolean(result.configured);
    state.modelConnectionMessage = result.message;
    state.modelConnectionStorage = result.storage;
    localStorage.setItem("learnnote.desk.model", JSON.stringify(state.model));
    window.dispatchEvent(new CustomEvent("learnnote:settings"));
    if (JSON.stringify(collect()) === snapshot) {
      $("apiKey").value = "";
      $("apiKey").placeholder = result.configured
        ? "已保存；留空继续使用，填写可替换"
        : "填写 API Key";
      if (!window.LearnNoteSettings?.modelSaved()) $("settingsDialog").close();
      notice(result.message);
    } else {
      $("settingsStatus").textContent =
        result.message + " 保存期间的新修改仍在此处，尚未保存。";
      window.LearnNoteSettings?.updateDirty();
    }
  } catch (error) {
    $("settingsStatus").textContent = "未能保存：" + error.message;
  } finally {
    $("savePreferences").disabled = false;
  }
};
$("theme").onclick = () => {
  const dark = document.body.classList.toggle("dark");
  localStorage.setItem("learnnote.desk.theme", dark ? "dark" : "light");
};
async function drawReview() {
  const card = state.cards[0];
  $("reviewContent").innerHTML = card
    ? `<p class="muted">待复习 ${state.cards.length} 张</p><h3>${esc(card.front)}</h3><label for="reviewReflection">先用自己的话解释要点；回答不会发送给模型</label><textarea id="reviewReflection" rows="3" maxlength="2000"></textarea><button id="recordReflection" class="primary">记录解释并显示答案</button><button id="skipReflection">跳过解释</button><p id="reviewReflectionStatus" role="status"></p><button id="reveal" class="primary" hidden>显示答案</button><div id="answer" hidden><p class="review-answer">${esc(card.back)}</p><div id="reviewSources"></div><div class="rating">${["忘记了", "有些困难", "记住了", "很轻松"].map((label, i) => `<button data-rating="${i + 1}">${label}</button>`).join("")}</div></div>`
    : '<p>今天的复习已完成。</p><p class="muted">你可以回到笔记，继续阅读和整理。</p>';
  if (card) {
    const revealAnswer = () => {
      $("answer").hidden = false;
      $("reveal").hidden = true;
      $("recordReflection").hidden = true;
      $("skipReflection").hidden = true;
      $("reviewReflection").hidden = true;
    };
    $("reveal").onclick = revealAnswer;
    $("recordReflection").onclick = async () => {
      if (!$("reviewReflection").value.trim()) {
        $("reviewReflectionStatus").textContent = "写一句解释，或选择跳过本次解释。";
        return;
      }
      $("recordReflection").disabled = true;
      $("skipReflection").disabled = true;
      try {
        await api("/api/study/activity", { method: "POST", body: JSON.stringify({ kind: "self_assessment", source_id: `card:${card.card_id}` }) });
        $("reviewReflectionStatus").textContent = "自我解释动作已保存在本机；解释文本未保存。";
        revealAnswer();
      } catch (error) {
        $("reviewReflectionStatus").textContent = error.message || "无法保存自我解释记录。";
        $("recordReflection").disabled = false;
        $("skipReflection").disabled = false;
      }
    };
    $("skipReflection").onclick = revealAnswer;
    $("reviewSources").innerHTML = (card.source_evidence_ids || [])
      .map((id) => `<button data-evidence="${esc(id)}">查看出处</button>`)
      .join("");
    try {
      const schedule = await api(`/api/study/cards/${encodeURIComponent(card.card_id)}/schedule-preview`);
      if(state.cards[0]?.card_id !== card.card_id || !$("reviewDialog").open) return;
      for (const choice of schedule.choices) {
        const button = $("reviewContent").querySelector(`[data-rating="${choice.rating}"]`);
        if(!button) continue;
        const seconds = choice.interval_seconds;
        const label = seconds < 3600 ? `${Math.max(1,Math.round(seconds/60))} 分钟后` : seconds < 86400 ? `${Math.round(seconds/3600)} 小时后` : `${Math.round(seconds/86400)} 天后`;
        const small = document.createElement("small"); small.textContent = label; button.append(small);
      }
    } catch { /* Review remains usable if only the preview request fails. */ }
  }
}
async function startReview(courseId = "") {
  $("reviewDialog").showModal();
  $("reviewContent").textContent = "正在读取…";
  try {
    await api("/api/study/plan/initialize", {
      method: "POST",
      body: JSON.stringify({
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }),
    });
    state.cards = (
      await api(`/api/study/due?course_id=${encodeURIComponent(courseId)}`)
    ).cards;
    drawReview();
  } catch (error) {
    $("reviewContent").textContent = error.message;
  }
}
$("review").onclick = () => startReview();

$("reviewContent").onclick = async (e) => {
  const button = e.target.closest("[data-rating],[data-evidence]");
  if (!button) return;
  button.disabled = true;
  try {
    if (button.dataset.evidence) {
      const data = await api(
        `/api/knowledge/evidence/${button.dataset.evidence}`,
      );
      const p = document.createElement("p");
      p.className = "review-answer";
      p.textContent = `${data.evidence.title || "出处"} · ${data.evidence.locator || ""}\n${data.evidence.text}`;
      button.replaceWith(p);
      return;
    }
    for (const b of $("reviewContent").querySelectorAll("[data-rating]"))
      b.disabled = true;
    const cardId = state.cards[0].card_id;
    if(state.reviewSubmission?.cardId !== cardId) state.reviewSubmission = {cardId,key:crypto.randomUUID()};
    const result = await api(`/api/study/cards/${cardId}/review`, {
      method: "POST",
      body: JSON.stringify({
        rating: Number(button.dataset.rating),
        idempotency_key: state.reviewSubmission.key,
      }),
    });
    state.reviewSubmission = null;
    if(result.card?.due_at) notice(`已记录，下次复习：${new Date(result.card.due_at).toLocaleString()}`);
    state.cards.shift();
    drawReview();
  } catch (error) {
    failure(error);
    for (const b of $("reviewContent").querySelectorAll("button"))
      b.disabled = false;
  }
};
window.addEventListener("beforeunload", (e) => {
  if (
    (state.editing && $("noteText").value !== state.text) ||
    $("annotationText").value.trim()
  ) {
    e.preventDefault();
    e.returnValue = "";
  }
});
async function loadKey() {
  try {
    return await loadModelConnection(state);
  } catch {
    // Older/public backends retain explicit per-page configuration.
    state.modelConnectionReady = false;
  }
}
async function initialize() {
  try {
    state.health = await api("/health");
    for (const provider of state.health.model_provider_presets || []) {
      if (!provider.key || !provider.base_url) continue;
      presets[provider.key] = [provider.base_url, provider.model];
      if (
        ![...$("provider").options].some(
          (option) => option.value === provider.key,
        )
      )
        $("provider").append(
          Object.assign(document.createElement("option"), {
            value: provider.key,
            textContent: provider.label || provider.key,
          }),
        );
    }
    if (!state.model.base_url && state.health.default_llm_base_url)
      state.model = {
        base_url: state.health.default_llm_base_url,
        model: state.health.default_llm_model,
        provider: state.health.default_llm_provider,
        use_saved_connection: Boolean(
          state.health.default_use_saved_connection,
        ),
      };
    await loadKey();
    await refresh();
    await applyRoute({ initial: true });
    window.LearnNoteUpdates?.startupCheck?.().catch(() => {});
  } catch (error) {
    failure(error);
  }
  setInterval(() => {
    if (!document.hidden || state.reading?.notify) refresh().catch(() => {});
  }, 5000);
}
initialize();

$("regenerate").onclick = async () => {
  const reuseTranscript =
    state.selected?.transcript_path &&
    !state.selected?.media_path &&
    !state.selected?.source_media_path;
  if (
    !guard() ||
    !confirm(
      reuseTranscript
        ? "使用已有字幕和当前模型重新生成总结？不下载视频或重复转写，手动修改仍保留。"
        : "使用当前模型设置重新整理？会创建新笔记，保留原笔记及修改。",
    )
  )
    return;
  $("regenerate").disabled = true;
  try {
    const result = await api(
      `/api/tasks/${state.selected.id}/${reuseTranscript ? "retry-summary" : "rerun-from-media"}`,
      { method: "POST", body: JSON.stringify(options()) },
    );
    await openItem({ ...result.task, id: result.task_id, kind: "task" });
    await refresh();
  } catch (error) {
    failure(error);
  } finally {
    $("regenerate").disabled = false;
  }
};

function readRoute() {
  const [path, params = ""] = location.hash.slice(1).split("?");
  const query = new URLSearchParams(params || location.search);
  const match = path.match(/^(task|material)\/(.+)$/);
  try {
    return {
      kind: match?.[1] || "task",
      id: match ? decodeURIComponent(match[2]) : query.get("task"),
      tab: query.get("tab"),
      view: ["settings", "diagnostics"].includes(path)
        ? path
        : query.get("view"),
    };
  } catch {
    return { invalid: true };
  }
}
async function applyRoute({ initial = false } = {}) {
  const route = readRoute();
  if (!initial && !guard()) {
    history.replaceState(
      null,
      "",
      state.selected
        ? `#${state.selected.kind}/${encodeURIComponent(state.selected.id)}`
        : location.pathname,
    );
    return;
  }
  if (route.invalid) {
    notice("链接格式无效，请从左侧重新选择笔记。");
    return;
  }
  const epoch = (state.routeEpoch = (state.routeEpoch || 0) + 1);
  let item =
    route.id &&
    state.items.find((i) => i.kind === route.kind && i.id === route.id);
  if (route.id && !item && !initial) {
    await refresh();
    item = state.items.find((i) => i.kind === route.kind && i.id === route.id);
  }
  if (epoch !== state.routeEpoch) return;
  if (
    item &&
    (state.selected?.id !== item.id || state.selected?.kind !== item.kind)
  )
    await openItem(item, { remember: !initial, check: false });
  else if (route.id && !item) {
    notice("这份内容不存在或已被删除，请从左侧重新选择。");
    return;
  } else if (!route.id && !route.view && !initial)
    showHome({ remember: false, check: false });
  if (epoch !== state.routeEpoch) return;
  if (route.view === "settings") {
    if (!$("settingsDialog").open) $("settings").click();
    else
      $("settingsDialog")
        .querySelector("[data-settings-section][aria-pressed=true]")
        ?.focus();
  } else if (route.view === "diagnostics" || route.tab === "diagnostics") {
    if (state.selected?.kind === "task") await workspaceTools.diagnostics();
    else await workspaceTools.storage();
  } else if (item && route.tab === "qa") window.LearnNoteAssistant?.open();
  else if (item && ["transcript", "media", "source"].includes(route.tab))
    await openSource();
  else if (item && ["frames", "slices"].includes(route.tab))
    $("sourceFrames")?.click();
}
window.addEventListener("hashchange", () => applyRoute().catch(failure));

const workspaceTools = installTools({
  state,
  options,
  openItem,
  refresh,
  notice,
  guard,
  startReview,
  reloadAnnotations: () => loadAnnotations(state.epoch).catch(failure),
});

installProductWorkspace({
  tools: workspaceTools,
  showHome,
  state,
  options,
  openItem,
  openSource,
  openInlineSource,
  refresh,
  notice,
  guard,
  loadKey,
});

installSettings({ state, notice, loadKey, guard });
installConnections({ state, notice, loadKey });

window.addEventListener("learnnote:annotations", () =>
  loadAnnotations(state.epoch).catch(failure),
);

installInteractions({ state, drawList, showHome, navigateBack });
installLayout();
installProfile({state, notice, startReview});
$("review").onclick = () => workspaceTools.studySettings();
