import { installSettings } from "/web/desk-settings.js";
import { installProductWorkspace } from "/web/desk-product.js";
import { installTools } from "/web/desk-tools.js";
import { api, escapeHtml as esc, timestamp, taskAsset } from "/web/desk-api.js";
const $ = (id) => document.getElementById(id);
let renderedCues = [],
  activeCueIndex = -1;
const state = {
  items: [],
  selected: null,
  epoch: 0,
  text: "",
  revision: "",
  editing: false,
  input: "url",
  busy: false,
  refreshing: false,
  cards: [],
  key: "",
  model: {},
  health: {},
};
const presets = {
  deepseek: ["https://api.deepseek.com/v1", "deepseek-chat"],
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
function guard() {
  const dirty =
    (state.editing && $("noteText").value !== state.text) ||
    $("annotationText").value.trim();
  return !dirty || confirm("还有未保存的修改或补充。放弃并离开？");
}
function options() {
  if (
    state.model.base_url &&
    !state.key &&
    state.model.base_url !== state.health.default_llm_base_url &&
    !/^http:\/\/(127\.0\.0\.1|localhost)(:|\/)/.test(state.model.base_url)
  )
    throw new Error("请在设置中填写当前模型服务的 Key，再开始整理。");
  return {
    ...state.processing,
    summary_depth: $("depth").value,
    note_style:
      ($("createDialog").open ? $("taskStyle")?.value : "") ||
      state.processing?.note_style ||
      "study",
    note_template:
      $("taskTemplate")?.value || state.processing?.note_template || "standard",
    visual_understanding: $("vision").checked,
    local_ocr: Boolean($("localOcr")?.checked),
    ...(state.model.base_url
      ? { llm_base_url: state.model.base_url, llm_model: state.model.model }
      : {}),
    ...(state.key ? { llm_api_key: state.key } : {}),
  };
}
function sourcePath(s = state.selected) {
  return `/api/tasks/editions/${s.kind}/${encodeURIComponent(s.id)}`;
}
function drawList() {
  const query = $("search").value.trim().toLowerCase();
  const rows = state.items.filter((item) =>
    item.title.toLowerCase().includes(query),
  );
  $("notes").innerHTML = rows.length
    ? rows
        .map(
          (item) =>
            `<button data-id="${esc(item.id)}" data-kind="${item.kind}" aria-current="${state.selected?.id === item.id && state.selected?.kind === item.kind}"><strong>${esc(item.title || "未命名笔记")}</strong><small>${item.kind === "material" ? "资料原文" : statusLabel(item)}${item.updated_at ? " · " + esc(item.updated_at.slice(0, 10)) : ""}</small></button>`,
        )
        .join("")
    : `<p class="muted" style="padding:12px">${query ? "没有匹配的笔记" : "添加内容后，笔记会出现在这里。"}</p>`;
}
function statusLabel(task) {
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
async function refresh() {
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
    window.dispatchEvent(new CustomEvent("learnnote:library"));
    throw error;
  } finally {
    state.refreshing = false;
  }
}
async function openItem(item) {
  if (!guard()) return;
  state.editing = false;
  $("editor").hidden = true;
  $("document").hidden = false;
  state.selected = item;
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
}
async function loadEdition(epoch) {
  const selected = state.selected;
  const edition = await api(sourcePath(selected));
  if (epoch !== state.epoch || state.editing) return;
  state.text = edition.text;
  state.revision = edition.revision;
  renderNote();
}
function renderNote() {
  LearnNoteMarkdown.configure({
    safeNoteMediaUrl: (value) =>
      state.selected?.kind === "task"
        ? taskAsset(value, state.selected.id)
        : "",
  });
  const heading = state.text.trim().startsWith("# ")
    ? ""
    : `<h1>${esc(state.selected.title)}</h1>`;
  $("document").innerHTML =
    heading +
    (state.text.trim()
      ? LearnNoteMarkdown.markdownToHtml(state.text)
      : '<p class="muted">笔记准备好后会显示在这里，你可以先查看处理进度。</p>');
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
}
function renderStatus() {
  const t = state.selected;
  $("regenerate").hidden = t.kind !== "task" || t.status !== "success";
  const panel = $("taskStatus");
  panel.hidden = t.kind !== "task" || t.status === "success";
  if (panel.hidden) return;
  panel.innerHTML = `<strong>${esc(statusLabel(t))}</strong><p>${esc(t.message || "")}</p>${t.awaiting_confirmation ? '<button data-task-action="start">确认并开始整理</button>' : ["failed", "cancelled"].includes(t.status) ? '<button data-task-action="resume">从已有进度恢复</button>' : `<progress max="100" value="${Number(t.progress) || 0}"></progress><button data-task-action="cancel">取消任务</button>`}`;
}
async function loadAnnotations(epoch) {
  const s = state.selected;
  const value = await api(`/api/personal/${s.kind}/${s.id}`);
  if (epoch !== state.epoch) return;
  $("annotationList").innerHTML = value.annotations
    .map((a) => `<div class="annotation">${esc(a.text)}</div>`)
    .join("");
}
function closeSource() {
  $("sourcePanel").hidden = true;
  document.body.classList.remove("source-open");
  $("player").pause();
}
async function openSource(seconds) {
  renderedCues = [];
  activeCueIndex = -1;
  const epoch = state.epoch,
    s = state.selected;
  $("sourcePanel").hidden = false;
  document.body.classList.add("source-open");
  $("sourceContent").textContent = "正在打开原始来源…";
  $("player").hidden = true;
  try {
    if (s.kind === "material") {
      const data = await api(`/api/library/materials/${s.id}/content`);
      if (epoch !== state.epoch) return;
      $("sourceContent").textContent = data.text;
      return;
    }
    const data = await api(`/api/tasks/${s.id}/transcript`);
    if (epoch !== state.epoch) return;
    const cues = data.segments || [];
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
    const player = $("player");
    player.hidden = false;
    const url = `/api/tasks/${s.id}/media`;
    if (player.getAttribute("src") !== url) player.src = url;
    if (seconds !== undefined) {
      player.currentTime = seconds;
      player.play().catch(() => {});
    }
  } catch (error) {
    if (epoch === state.epoch) $("sourceContent").textContent = error.message;
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
      panel = $("sourcePanel").getBoundingClientRect(),
      video = $("player").getBoundingClientRect();
    if (bounds.bottom > panel.bottom - 20 || bounds.top < video.bottom + 10)
      $("sourcePanel").scrollTop += bounds.top - video.bottom - 18;
  }
});
$("player").addEventListener("error", () => {
  if (!$("sourcePanel").hidden)
    notice("本地视频暂不可播放；仍可阅读字幕或打开原网页。");
});
$("sourceContent").onclick = (e) => {
  const cue = e.target.closest("[data-time]");
  if (cue) {
    $("player").currentTime = Number(cue.dataset.time);
    $("player")
      .play()
      .catch(() => {});
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
$("menu").onclick = () => {
  $("menu").setAttribute(
    "aria-expanded",
    String(document.body.classList.toggle("menu-open")),
  );
};
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
    await api(`/api/personal/${s.kind}/${s.id}`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    if (epoch !== state.epoch) return;
    $("annotationText").value = "";
    await loadAnnotations(epoch);
  } catch (error) {
    failure(error);
  } finally {
    button.disabled = false;
  }
};
function create() {
  if (!$("createDialog").open) $("createDialog").showModal();
  window.dispatchEvent(new CustomEvent("learnnote:create"));
}
$("newNote").onclick = create;
$("welcomeNew").onclick = create;
for (const button of document.querySelectorAll("[data-close]"))
  button.onclick = () => button.closest("dialog").close();
for (const button of document.querySelectorAll("[data-input]"))
  button.onclick = () => {
    state.input = button.dataset.input;
    for (const el of document.querySelectorAll("[data-input]"))
      el.setAttribute("aria-pressed", String(el === button));
    for (const kind of ["url", "file", "browser"])
      $(kind + "Input").hidden = kind !== state.input;
    $("createSubmit").hidden = state.input === "browser";
    $("generationOptions").hidden = state.input === "browser";
    $("createStatus").textContent = "";
  };
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
      if (kind === "task") data.append("options", JSON.stringify(options()));
      result = await api(
        kind === "task"
          ? "/api/tasks/from-local"
          : "/api/library/materials/import",
        { method: "POST", body: data },
      );
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
  if (!button) return;
  button.disabled = true;
  try {
    await api(`/api/tasks/${state.selected.id}/${button.dataset.taskAction}`, {
      method: "POST",
      body: JSON.stringify(
        button.dataset.taskAction === "cancel" ? {} : options(),
      ),
    });
    await refresh();
  } catch (error) {
    failure(error);
  } finally {
    button.disabled = false;
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
  state.model = {
    provider: $("provider").value,
    base_url: $("baseUrl").value.trim(),
    model: $("model").value.trim(),
  };
  state.key = $("apiKey").value.trim();
  try {
    if (state.key && window.pywebview?.api?.save_model_key) {
      await window.pywebview.api.save_model_key(
        state.model.provider,
        state.key,
      );
    }
    localStorage.setItem("learnnote.desk.model", JSON.stringify(state.model));
    window.dispatchEvent(new CustomEvent("learnnote:settings"));
    $("settingsDialog").close();
    notice("设置已保存");
  } catch (error) {
    $("settingsStatus").textContent = error.message;
  }
};
$("theme").onclick = () => {
  const dark = document.body.classList.toggle("dark");
  localStorage.setItem("learnnote.desk.theme", dark ? "dark" : "light");
};
async function drawReview() {
  const card = state.cards[0];
  $("reviewContent").innerHTML = card
    ? `<p class="muted">待复习 ${state.cards.length} 张</p><h3>${esc(card.front)}</h3><button id="reveal" class="primary">显示答案</button><div id="answer" hidden><p class="review-answer">${esc(card.back)}</p><div id="reviewSources"></div><div class="rating">${["忘记了", "有些困难", "记住了", "很轻松"].map((label, i) => `<button data-rating="${i + 1}">${label}</button>`).join("")}</div></div>`
    : '<p>今天的复习已完成。</p><p class="muted">你可以回到笔记，继续阅读和整理。</p>';
  if (card) {
    $("reveal").onclick = () => {
      $("answer").hidden = false;
      $("reveal").hidden = true;
    };
    $("reviewSources").innerHTML = (card.source_evidence_ids || [])
      .map((id) => `<button data-evidence="${esc(id)}">查看出处</button>`)
      .join("");
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
    await api(`/api/study/cards/${state.cards[0].card_id}/review`, {
      method: "POST",
      body: JSON.stringify({
        rating: Number(button.dataset.rating),
        idempotency_key: crypto.randomUUID(),
      }),
    });
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
  if (state.model.provider && window.pywebview?.api?.load_model_key) {
    try {
      const provider=state.model.provider;
      const value = await window.pywebview.api.load_model_key(provider);
      if (value.configured && state.model.provider===provider) state.key = value.api_key;
    } catch {}
  }
}
window.addEventListener("pywebviewready", loadKey);
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
      };
    await loadKey();
    await refresh();
    const query = new URLSearchParams(location.search);
    const match =
      location.hash.match(/^#(task|material)\/(.+)$/) ||
      (query.get("task") ? ["", "task", query.get("task")] : null);
    const item =
      match &&
      state.items.find(
        (i) => i.kind === match[1] && i.id === decodeURIComponent(match[2]),
      );
    if (item) await openItem(item);
    if (query.get("view") === "settings") $("settings").click();
    else if (
      query.get("view") === "diagnostics" ||
      query.get("tab") === "diagnostics"
    ) {
      if (state.selected?.kind === "task") await workspaceTools.diagnostics();
      else await workspaceTools.storage();
    } else if (item && query.get("tab") === "qa")
      window.LearnNoteAssistant?.open();
    else if (
      item &&
      ["transcript", "media", "source"].includes(query.get("tab"))
    )
      await openSource();
    else if (item && ["frames", "slices"].includes(query.get("tab")))
      $("sourceFrames")?.click();

    if (!item && state.items.length) {
      $("welcomeNew").innerHTML = "新建笔记 <span>↗</span>";
    }
  } catch (error) {
    failure(error);
  }
  setInterval(() => {
    if (!document.hidden || state.reading?.notify) refresh().catch(() => {});
  }, 5000);
}
initialize();

$("regenerate").onclick = async () => {
  if (
    !guard() ||
    !confirm("使用当前模型设置重新整理？会创建新笔记，保留原笔记及修改。")
  )
    return;
  $("regenerate").disabled = true;
  try {
    const result = await api(
      `/api/tasks/${state.selected.id}/rerun-from-media`,
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

window.addEventListener("hashchange", () => {
  const match = location.hash.match(/^#(task|material)\/(.+)$/);
  const item =
    match &&
    state.items.find(
      (i) => i.kind === match[1] && i.id === decodeURIComponent(match[2]),
    );
  if (
    item &&
    (state.selected?.id !== item.id || state.selected?.kind !== item.kind)
  )
    openItem(item).catch(failure);
});

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
  state,
  options,
  openItem,
  openSource,
  refresh,
  notice,
  guard,
  loadKey,
});

installSettings({ state, notice, loadKey });

window.addEventListener("learnnote:annotations", () =>
  loadAnnotations(state.epoch).catch(failure),
);
