import { assistantStream } from "/web/desk-chat-stream.js";
import { createDraftStore } from "/web/desk-drafts.js";
import { installSummaryVersions } from "/web/desk-summary-versions.js";
import { api, escapeHtml as esc, timestamp, taskAsset } from "/web/desk-api.js";
const svg = (paths) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
const icons = {
  book: svg('<path d="M3 4h7l2 2 2-2h7v16h-7l-2 1-2-1H3zM12 6v15"/>'),
  plus: svg('<path d="M12 5v14M5 12h14"/>'),
  ai: svg(
    '<path d="m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6z"/>',
  ),
  settings: svg(
    '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
  ),
  menu: svg('<path d="M4 6h16M4 12h16M4 18h16"/>'),
  refresh: svg('<path d="M20 8a8 8 0 1 0 0 8M20 3v5h-5"/>'),
  theme: svg('<path d="M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11z"/>'),
  history: svg('<path d="M3 5v5h5M3 10a9 9 0 1 1 1 8M12 7v5l4 2"/>'),
  outline: svg('<path d="M9 5h12M9 12h12M9 19h12M3 5h1M3 12h1M3 19h1"/>'),
  review: svg('<path d="M5 4h14v17l-7-4-7 4zM8 9l3 3 5-5"/>'),
  folder: svg('<path d="M3 6h7l2 3h9v11H3z"/>'),
};
export function installProductWorkspace(ctx) {
  const {
      state,
      options,
      openItem,
      openSource,
      refresh,
      notice,
      guard,
      loadKey,
    } = ctx,
    $ = (id) => document.getElementById(id);
  for (const [id, icon, label] of [
    ["newNote", "plus", "新建笔记"],
    ["settings", "settings", "设置"],
    ["review", "review", "复习"],
    ["courses", "folder", "课程"],

    ["refresh", "refresh", ""],
    ["theme", "theme", ""],
  ])
    if ($(id))
      $(id).innerHTML = icons[icon] + (label ? `<span>${label}</span>` : "");
  document.querySelector(".brand").innerHTML =
    icons.book + "<strong>LearnNote</strong>";
  for (const [id, path, label] of [
    ["edit", '<path d="m4 16 11-11 4 4L8 20H4zM13 7l4 4"/>', "编辑"],
    [
      "source",
      '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m10 8 6 4-6 4z"/>',
      "来源",
    ],
    ["export", '<path d="M12 3v12M8 11l4 4 4-4M4 16v5h16v-5"/>', "导出"],
    [
      "moreTools",
      '<path d="M4 5h6v6H4zM14 5h6v6h-6zM4 15h6v6H4zM14 15h6v6h-6z"/>',
      "学习工具",
    ],
  ]) {
    const button = $(id);
    if (!button) continue;
    button.innerHTML = svg(path) + `<span>${label}</span>`;
    button.setAttribute("aria-label", label);
    button.title = label;
  }
  $("export").hidden = false;
  $("generationOptions").open = false;
  const playback = document.createElement("div");
  playback.className = "playback-controls";
  playback.innerHTML =
    '<label>播放速度<select id="playbackRate"><option value="0.75">0.75×</option><option value="1" selected>1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></label><label class="check"><input id="followTranscript" type="checkbox" checked>跟随字幕</label>';
  $("sourcePanel").querySelector("header").after(playback);
  $("playbackRate").onchange = () => {
    $("player").defaultPlaybackRate = Number($("playbackRate").value);
    $("player").playbackRate = Number($("playbackRate").value);
  };
  const toolbar = document.querySelector(".toolbar");
  const launch = document.createElement("button");
  launch.id = "aiAssistant";
  launch.className = "assistant-launch";
  launch.innerHTML = icons.ai + "<span>全局助手</span>";
  launch.setAttribute("aria-expanded", "false");
  toolbar.append(launch);
  const pane = document.createElement("aside");
  pane.id = "assistantPanel";
  pane.className = "assistant-panel";
  pane.hidden = true;
  pane.innerHTML = `<header><strong>${icons.ai} 全局助手</strong><div><button id="fullAssistant" title="铺满工作区">全屏</button><button id="closeAssistant" aria-label="关闭 全局助手">×</button></div></header><div class="assistant-context"><small>当前上下文</small><strong id="assistantContext">尚未选择笔记</strong><span id="assistantModel"></span></div><div id="assistantHistory" class="assistant-history" role="log" aria-live="polite"></div><div class="assistant-prompts"><button data-prompt="你有哪些功能？怎么使用？">使用帮助</button><button data-prompt="总结这份内容的核心观点，并给出对应出处">总结要点</button><button data-prompt="解释这份内容中最重要的概念和它们的关系">解释概念</button><button data-prompt="根据原文给出三道自测问题，并附上参考答案和出处">帮我自测</button></div><form id="aiForm"><label class="sr-only" for="aiQuestion">向全局助手提问</label><textarea id="aiQuestion" maxlength="1000" rows="3" required placeholder="问操作方法、查资料，或围绕当前内容提问…"></textarea><footer><small id="aiStatus" role="status"></small><button id="aiStop" type="button" hidden>停止</button><button id="aiSend" class="primary">发送</button></footer></form>`;
  document.body.append(pane);
  const skillControls = document.createElement("div");
  skillControls.className = "assistant-skill-controls";
  skillControls.innerHTML =
    '<label for="assistantSkill">选择能力</label><div><select id="assistantSkill" aria-label="选择助理 Skill"><option value="auto">自动选择 Skill（本地匹配）</option></select><button id="skillCatalog">功能目录</button></div><p id="skillExecution" role="status">每次调用会显示 Skill 与上下文范围</p>';
  const assistantOptions = document.createElement("details");
  assistantOptions.className = "assistant-options";
  assistantOptions.innerHTML = "<summary>回答选项</summary>";
  assistantOptions.append(
    skillControls,
    pane.querySelector(".assistant-context"),
  );
  pane.querySelector("#aiForm").before(assistantOptions);
  const scopeLabel = document.createElement("p");
  scopeLabel.id = "assistantScope";
  scopeLabel.className = "assistant-scope";
  pane.querySelector("#aiForm").prepend(scopeLabel);
  pane.querySelectorAll("[data-prompt]").forEach((button, index) => {
    if (index > 1) button.hidden = true;
  });
  let skills = [],
    features = [];
  async function loadSkills() {
    try {
      const catalog = await api("/api/assistant/skills");
      skills = catalog.skills;
      features = catalog.features || [];
      for (const skill of skills)
        $("assistantSkill").append(
          Object.assign(document.createElement("option"), {
            value: skill.id,
            textContent: `${skill.name} · ${skill.requires_source ? "当前内容" : "全局"}`,
          }),
        );
    } catch (error) {
      $("skillExecution").textContent = "能力目录暂不可用：" + error.message;
    }
  }
  loadSkills();
  function skillInfo(id) {
    return (
      skills.find((s) => s.id === id) || {
        id: id || "note.qa",
        name: "历史内容问答",
        scope: "source",
        requires_source: true,
      }
    );
  }
  function openAction(id) {
    const settings = id.match(
      /^settings_(model|transcriber|notes|processing|appearance|storage)$/,
    );
    if (settings) {
      $("settings").click();
      document
        .querySelector(`[data-settings-section="${settings[1]}"]`)
        ?.click();
      return;
    }
    const actions = {
      create: () => $("newNote").click(),
      browser: () => {
        $("newNote").click();
        document.querySelector('[data-input="browser"]').click();
      },
      courses: () => $("courses").click(),
      review: () => $("review").click(),
      storage: () => ctx.tools.storage(),
      diagnostics: () =>
        state.selected?.kind === "task"
          ? ctx.tools.diagnostics()
          : ctx.tools.storage(),
      export: () =>
        state.selected
          ? $("export").click()
          : notice("先选择一份笔记，再导出。"),
      tools: () =>
        state.selected ? $("moreTools").click() : notice("先选择一份笔记。"),
      select_note: () => {
        document.body.classList.remove("sidebar-collapsed");
        document.body.classList.add("menu-open");
        window.dispatchEvent(new Event("resize"));
        $("search").focus();
      },
      home: () => ctx.showHome(),
    };
    if (Object.hasOwn(actions, id)) actions[id]();
  }
  $("skillCatalog").onclick = () => {
    const modal = document.createElement("dialog");
    modal.className = "skill-catalog-dialog";
    modal.innerHTML =
      '<header><h2>助手能力目录</h2><button aria-label="关闭">×</button></header><p class="muted">本地使用，无需登录。操作按钮只打开对应界面；不会自动删除或修改你的文件。</p><div class="skill-catalog">' +
      skills
        .map(
          (s) =>
            `<button data-pick-skill="${s.id}"><strong>${esc(s.name)}</strong><code>${esc(s.id)}</code><span>${esc(s.description)}</span><small>${s.requires_source ? "需要选中的来源" : s.scope === "library" ? "只读本地资料库" : "不自动读取笔记"} · ${s.execution === "local" ? "本地执行" : "配置模型或明确回退"}</small></button>`,
        )
        .join("") +
      '</div><footer><button id="clearGlobalAssistant">清空全局对话记录</button></footer>';
    document.body.append(modal);
    const featureMenu = document.createElement("details");
    featureMenu.innerHTML =
      '<summary>工作台功能入口</summary><div class="assistant-action-links">' +
      features
        .map(
          (f, i) => `<button data-feature-index="${i}">${esc(f.name)}</button>`,
        )
        .join("") +
      "</div>";
    modal.querySelector("footer").before(featureMenu);
    featureMenu.querySelectorAll("[data-feature-index]").forEach(
      (button) =>
        (button.onclick = () => {
          modal.close();
          openAction(features[Number(button.dataset.featureIndex)].action);
        }),
    );
    modal.querySelector("header button").onclick = () => modal.close();
    modal.addEventListener("close", () => modal.remove(), { once: true });
    modal.querySelectorAll("[data-pick-skill]").forEach(
      (b) =>
        (b.onclick = () => {
          $("assistantSkill").value = b.dataset.pickSkill;
          $("assistantSkill").dispatchEvent(new Event("change"));
          modal.close();
          $("aiQuestion").focus();
        }),
    );
    modal.querySelector("#clearGlobalAssistant").onclick = async () => {
      if (
        !confirm("清空全局帮助与通用问答历史？各笔记原有的内容问答记录仍保留。")
      )
        return;
      await api("/api/assistant/history?confirm=clear_assistant_history", {
        method: "DELETE",
      });
      modal.close();
      loadHistory();
    };
    modal.showModal();
  };
  $("assistantSkill").onchange = () => {
    const selected = skills.find((s) => s.id === $("assistantSkill").value);
    $("skillExecution").textContent = selected
      ? `${selected.name} · ${selected.id}：${selected.description}`
      : "根据问题选择 Skill；回复中显示实际调用。";
    $("assistantContext").textContent = selected
      ? selected.requires_source
        ? state.selected?.title || "等待选择来源"
        : selected.scope === "library"
          ? "本地资料库"
          : selected.scope === "conversation"
            ? "通用对话 · 不自动读资料"
            : "软件功能与状态 · 全局范围"
      : state.selected?.title || "全局范围 · 可直接提问";
  };

  let assistantEpoch = 0,
    pending = false,
    activeRequest = null;
  let draftStorage;
  try {
    draftStorage = localStorage;
  } catch {}
  const localThreads = new Map(),
    drafts = createDraftStore(draftStorage);
  let visibleSource = "",
    previousSkill = "";
  const saveDraft = () => {
    if (
      visibleSource &&
      drafts.set(visibleSource, $("aiQuestion").value) === false &&
      $("aiQuestion").value.trim()
    )
      $("aiStatus").textContent = "浏览器未能保存草稿，刷新前请先复制输入。";
  };
  $("aiQuestion").addEventListener("input", saveDraft);
  window.addEventListener("pagehide", saveDraft);
  $("aiQuestion").addEventListener("keydown", (event) => {
    if (
      event.key === "Enter" &&
      (event.ctrlKey || event.metaKey) &&
      !event.isComposing
    ) {
      event.preventDefault();
      if (!pending) $("aiForm").requestSubmit();
    }
  });
  $("aiSend").title = "发送 · Ctrl / ⌘ + Enter";
  function renderMessage(question, result, originalSource = state.selected) {
    const messageSource =
      result.skill && !result.skill.requires_source
        ? null
        : originalSource
          ? { ...originalSource }
          : null;
    const usedSkill = result.skill || skillInfo(result.skill_id);
    LearnNoteMarkdown.configure({
      safeNoteMediaUrl: (value) =>
        messageSource?.kind === "task"
          ? taskAsset(value, messageSource.id)
          : "",
    });
    const block = document.createElement("section");
    block.className = "assistant-turn";
    block.innerHTML = `<div class="assistant-question">${esc(question)}</div><details class="skill-trace"><summary>来源与处理方式</summary><strong>${esc(usedSkill.name)}</strong><code>${esc(usedSkill.id)}</code><em>${esc({ completed: "已完成", needs_source: "等待来源", needs_configuration: "需要配置", failed: "失败", local_extract: "摘录模式" }[result.execution?.state] || "对话记录")}</em><span>${usedSkill.requires_source ? esc(messageSource?.title || "当前内容") : usedSkill.scope === "library" ? "本地资料库 · 按关键词检索" : usedSkill.scope === "conversation" ? "通用对话 · 未自动读取资料" : "软件功能与状态 · 未读取笔记正文"} · ${result.source === "llm" ? "文字模型" : "本地执行 / 摘录"}</span></details><div class="assistant-answer">${LearnNoteMarkdown.markdownToHtml(result.answer || result.message || "没有返回回答。")}</div>${result.warning ? `<p class="muted">${esc(result.warning)}</p>` : ""}<div class="assistant-citations">${(result.citations || []).map((c, i) => `<button data-citation="${i}">${esc(c.label || c.time_range || "出处 " + (i + 1))}</button>`).join("")}</div><button class="save-ai-note">保存为我的补充</button>`;
    block.querySelectorAll("[data-citation]").forEach(
      (b) =>
        (b.onclick = async () => {
          const c = result.citations[Number(b.dataset.citation)];
          if (typeof c.start === "number") await openSource(c.start);
          else {
            const p = document.createElement("blockquote");
            p.textContent = c.text || "暂无可用的原文定位";
            b.after(p);
          }
        }),
    );
    block.querySelector(".save-ai-note").onclick = async (e) => {
      const s = messageSource;
      if (!s) return;
      const b = e.currentTarget;
      b.disabled = true;
      try {
        await api(`/api/personal/${s.kind}/${s.id}`, {
          method: "POST",
          body: JSON.stringify({
            text: `问题：${question}\n\n${result.answer || result.message || ""}`.slice(
              0,
              8000,
            ),
          }),
        });
        notice("已保存到当前笔记的个人补充。");
        window.dispatchEvent(new CustomEvent("learnnote:annotations"));
      } catch (err) {
        notice(err.message);
        b.disabled = false;
      }
    };
    if (!messageSource) block.querySelector(".save-ai-note").hidden = true;
    if (result.actions?.length) {
      const actions = document.createElement("div");
      actions.className = "assistant-action-links";
      for (const action of result.actions) {
        const b = document.createElement("button");
        b.textContent = action.label;
        b.onclick = () => openAction(action.id);
        actions.append(b);
      }
      block.append(actions);
    }
    return block;
  }
  async function loadHistory() {
    activeRequest?.abort();
    activeRequest = null;
    $("aiStop").hidden = true;
    const epoch = ++assistantEpoch,
      s = state.selected;
    if (visibleSource) drafts.set(visibleSource, $("aiQuestion").value);
    const nextScope = s ? `${s.kind}:${s.id}` : "global";
    if (visibleSource && visibleSource !== nextScope) previousSkill = "";
    visibleSource = nextScope;
    $("aiQuestion").value = drafts.get(visibleSource) || "";
    $("aiStatus").textContent = $("aiQuestion").value
      ? "已恢复未发送的草稿 · 仅保存在本机"
      : "";
    pending = false;
    $("aiSend").disabled = false;
    $("assistantHistory").replaceChildren();
    $("assistantScope").textContent = s ? `当前内容 · ${s.title}` : "自由提问";
    $("assistantContext").textContent = s?.title || "全局范围 · 不需要选择笔记";
    $("assistantModel").textContent = !s
      ? "使用帮助与工作环境可在本机直接使用"
      : s?.kind === "material"
        ? "当前文档 · 本地原文检索"
        : state.model.model || state.health.default_llm_model || "本地证据回答";
    try {
      const globalItems = (await api("/api/assistant/history")).items;
      const sourceItems =
        s?.kind === "task"
          ? (await api(`/api/tasks/${s.id}/qa`)).items
          : s
            ? localThreads.get(s.id) || []
            : [];
      const items = [...globalItems, ...sourceItems].sort((a, b) =>
        (a.created_at || "").localeCompare(b.created_at || ""),
      );
      if (epoch !== assistantEpoch) return;
      if (!previousSkill && visibleSource === "global")
        previousSkill = items.at(-1)?.skill?.id || "";
      for (const item of items)
        $("assistantHistory").append(renderMessage(item.question, item));
      if (!items.length)
        $("assistantHistory").innerHTML =
          '<div class="assistant-empty"><strong>有什么想问的？</strong><p>直接提问，或围绕当前内容继续聊。</p></div>';
      $("assistantHistory").scrollTop = $("assistantHistory").scrollHeight;
    } catch (e) {
      if (epoch === assistantEpoch) {
        $("aiStatus").textContent = e.message;
        const empty = document.createElement("div");
        empty.className = "assistant-empty";
        empty.innerHTML =
          '<strong>暂时无法读取对话记录</strong><p>草稿已保留，可以稍后重试。</p><button type="button">重新读取记录</button>';
        empty.querySelector("button").onclick = loadHistory;
        $("assistantHistory").replaceChildren(empty);
      }
    }
  }
  function toggleAssistant(open) {
    pane.hidden = !open;
    document.body.classList.toggle("assistant-visible", open);
    launch.setAttribute("aria-expanded", String(open));
    window.LearnNoteLayout?.refresh();
    if (open) {
      const scope = state.selected
        ? `${state.selected.kind}:${state.selected.id}`
        : "global";
      if (!pending || visibleSource !== scope) loadHistory();
      $("aiQuestion").focus();
    } else if (pane.contains(document.activeElement)) launch.focus();
  }
  launch.onclick = () => toggleAssistant(pane.hidden);
  $("closeAssistant").onclick = () => toggleAssistant(false);
  pane.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.querySelector("dialog[open]")) {
      event.preventDefault();
      toggleAssistant(false);
    }
  });
  $("fullAssistant").onclick = () => {
    const full = document.body.classList.toggle("assistant-full");
    $("fullAssistant").textContent = full ? "还原" : "全屏";
    $("fullAssistant").setAttribute("aria-pressed", String(full));
    window.LearnNoteLayout?.refresh();
  };
  window.addEventListener("learnnote:selection", () => {
    if (!pane.hidden) loadHistory();
    else {
      activeRequest?.abort();
      activeRequest = null;
      assistantEpoch++;
      pending = false;
      if (visibleSource) drafts.set(visibleSource, $("aiQuestion").value);
      visibleSource = "";
      previousSkill = "";
      $("aiStop").hidden = true;
      $("aiSend").disabled = false;
    }
    updateReadingContext();
  });
  pane.querySelectorAll("[data-prompt]").forEach(
    (b) =>
      (b.onclick = () => {
        $("aiQuestion").value = b.dataset.prompt;
        saveDraft();
        $("aiQuestion").focus();
      }),
  );
  $("aiStop").onclick = () => activeRequest?.abort();
  $("aiForm").onsubmit = async (e) => {
    e.preventDefault();
    if (pending) return;
    const s = state.selected;
    const question = $("aiQuestion").value.trim();
    if (!question) return;
    saveDraft();
    const epoch = ++assistantEpoch;
    pending = true;
    $("aiSend").disabled = true;
    const controller = new AbortController();
    activeRequest = controller;
    const timeout = setTimeout(() => controller.abort("timeout"), 185000);
    $("aiStop").hidden = false;
    $("aiStatus").textContent = "正在准备回答…";
    const streamBlock = document.createElement("section");
    streamBlock.className = "assistant-turn streaming-turn";
    streamBlock.setAttribute("aria-live", "off");
    streamBlock.innerHTML = `<div class="assistant-question">${esc(question)}</div><div class="assistant-thinking"><span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span><span>正在准备回答…</span></div><div class="assistant-answer"></div>`;
    $("assistantHistory").querySelector(".assistant-empty")?.remove();
    $("assistantHistory").append(streamBlock);
    $("assistantHistory").scrollTop = $("assistantHistory").scrollHeight;
    let streamedText = "",
      paintTimer = 0;
    const paint = () => {
      paintTimer = 0;
      if (epoch !== assistantEpoch) return;
      const history = $("assistantHistory");
      const following =
        history.scrollHeight - history.scrollTop - history.clientHeight < 100;
      LearnNoteMarkdown.configure({
        safeNoteMediaUrl: (value) =>
          s?.kind === "task" ? taskAsset(value, s.id) : "",
      });
      streamBlock.querySelector(".assistant-answer").innerHTML =
        LearnNoteMarkdown.markdownToHtml(streamedText);
      if (following) history.scrollTop = history.scrollHeight;
    };
    const streamingOptions = {
      signal: controller.signal,
      onDelta(text) {
        if (epoch !== assistantEpoch) return;
        streamedText += text;
        streamBlock.querySelector(".assistant-thinking").hidden = true;
        $("aiStatus").textContent = "正在回答…";
        if (!paintTimer) paintTimer = setTimeout(paint, 60);
      },
      onStatus(message) {
        if (epoch === assistantEpoch && !streamedText)
          streamBlock.querySelector(
            ".assistant-thinking > span:last-child",
          ).textContent = message;
      },
    };
    try {
      $("skillExecution").textContent = "正在选择 Skill…";
      const plan = await api("/api/assistant/route", {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({
          question,
          skill: $("assistantSkill").value,
          has_source: Boolean(s),
          previous_skill: previousSkill,
        }),
      });
      if (epoch !== assistantEpoch) return;
      previousSkill = plan.skill.id;
      $("skillExecution").textContent =
        `${plan.skill.name} · ${plan.skill.id} → ${plan.needs_source ? "等待选择来源" : plan.skill.requires_source ? "读取选中的内容" : plan.skill.execution === "local" ? "本地能力" : "调用配置的文字模型"}`;
      $("assistantContext").textContent = plan.skill.requires_source
        ? s?.title || "等待选择来源"
        : {
            "product.help": "软件功能说明",
            "product.status": "本机工作状态",
            "library.search": "本地资料库",
            "general.chat": "通用对话 · 不自动读取笔记",
          }[plan.skill.id] || "全局范围";
      $("assistantModel").textContent =
        plan.skill.execution === "local"
          ? "本地执行 · 无需模型 Key"
          : plan.skill.requires_source && s?.kind === "material"
            ? "当前文档 · 原文检索"
            : state.model.model ||
              state.health.default_llm_model ||
              "需要配置文字模型";
      let result;
      if (plan.needs_source) {
        result = {
          answer:
            "这个 Skill 需要先选择一份笔记或资料。选择后再发送问题；没有读取其他文件。",
          skill: plan.skill,
          source: "local",
          actions: [{ id: "select_note", label: "选择笔记" }],
          execution: { state: "needs_source" },
        };
      } else if (!plan.skill.requires_source) {
        result = await assistantStream(
          "/api/assistant/execute/stream",
          {
            question,
            skill: plan.skill.id,
            ...(plan.skill.id === "general.chat" ? { options: options() } : {}),
          },
          streamingOptions,
        );
      } else {
        result =
          s.kind === "task"
            ? await assistantStream(
                `/api/tasks/${s.id}/qa/stream`,
                { question, skill_id: plan.skill.id, options: options() },
                streamingOptions,
              )
            : await api(`/api/library/materials/${s.id}/ask`, {
                method: "POST",
                signal: controller.signal,
                body: JSON.stringify({ question }),
              });
        result = { ...result, skill: plan.skill };
        if (
          ["study.quiz", "note.summary"].includes(plan.skill.id) &&
          result.source !== "llm"
        ) {
          result.execution = { state: "local_extract" };
          result.warning =
            "当前返回本地原文摘录，未调用模型生成总结或自测题。可配置文字模型；也可以从学习工具手动创建复习卡。";
        }
      }
      if (epoch === assistantEpoch)
        $("skillExecution").textContent =
          `${plan.skill.name} · ${plan.skill.id} → ${result.execution?.state === "needs_source" ? "等待上下文" : result.execution?.state === "needs_configuration" ? "需要配置模型" : result.execution?.state === "failed" ? "执行失败" : result.execution?.state === "local_extract" ? "原文检索完成，未生成模型内容" : result.source === "llm" ? "模型回答完成" : "本地执行完成"}`;
      if (epoch !== assistantEpoch) return;
      $("assistantHistory").querySelector(".assistant-empty")?.remove();
      clearTimeout(paintTimer);
      streamBlock.replaceWith(renderMessage(question, result, s));
      if (s?.kind === "material" && result.skill?.requires_source)
        localThreads.set(s.id, [
          ...(localThreads.get(s.id) || []),
          { question, ...result, created_at: new Date().toISOString() },
        ]);
      if (
        $("aiQuestion").value.trim() === question &&
        !["failed", "needs_configuration", "needs_source"].includes(
          result.execution?.state,
        )
      )
        $("aiQuestion").value = "";
      saveDraft();
      $("assistantHistory").scrollTop = $("assistantHistory").scrollHeight;
      $("aiStatus").textContent =
        result.warning ||
        (result.source === "llm"
          ? "回答已保存，可查看出处"
          : "回答完成，重要内容请核对出处");
    } catch (error) {
      if (epoch === assistantEpoch) {
        clearTimeout(paintTimer);
        paint();
        streamBlock.querySelector(".assistant-thinking").hidden = true;
        const interrupted = controller.signal.aborted
          ? controller.signal.reason === "timeout"
            ? "等待回答超时，可以重新发送。"
            : "已停止。未完成的内容没有保存为回答。"
          : error.message || "回答中断，请重试。";
        const message = document.createElement("p");
        message.className = "muted";
        message.textContent = interrupted;
        streamBlock.append(message);
        $("aiStatus").textContent = interrupted;
        $("skillExecution").textContent =
          "本次调用失败，没有自动执行其他操作。";
      }
    } finally {
      clearTimeout(timeout);
      clearTimeout(paintTimer);
      if (activeRequest === controller) activeRequest = null;
      if (epoch === assistantEpoch) {
        $("aiStop").hidden = true;
        pending = false;
        $("aiSend").disabled = false;
      }
    }
  };
  const readerNav = document.createElement("div");
  readerNav.className = "reader-strip";
  readerNav.id = "readerStrip";
  readerNav.hidden = true;
  readerNav.innerHTML = `<div id="readerMetadata"></div><div><button id="openOutline">${icons.outline} 内容目录</button><button id="sourceFrames">画面索引</button><button id="openVersions">${icons.history} 历史版本</button><button id="focusReading">专注阅读</button></div>`;
  toolbar.after(readerNav);
  const pageContents = document.createElement("nav");
  pageContents.id = "pageContents";
  pageContents.setAttribute("aria-label", "当前笔记章节");
  pageContents.hidden = true;
  document.body.append(pageContents);
  function drawContents() {
    const headings = [...$("document").querySelectorAll("h2,h3")].filter(
      (h) => !h.closest("details:not([open])"),
    );
    pageContents.hidden =
      !state.selected ||
      !headings.length ||
      Number(state.reading?.width || 940) > 940;
    pageContents.innerHTML =
      "<span>目录</span>" +
      headings
        .map(
          (h, index) =>
            `<button data-section-index="${index}" style="--level:${Number(h.tagName.slice(1)) - 2}">${esc(h.textContent)}</button>`,
        )
        .join("");
    pageContents.querySelectorAll("button").forEach((button) => {
      button.onclick = () =>
        headings[Number(button.dataset.sectionIndex)].scrollIntoView({
          block: "start",
          behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "instant"
            : "smooth",
        });
    });
  }
  window.addEventListener("learnnote:document", drawContents);
  window.addEventListener("learnnote:settings", drawContents);
  window.addEventListener("learnnote:selection", () => {
    pageContents.hidden = true;
  });
  const outline = document.createElement("dialog");
  outline.id = "outlineDialog";
  document.body.append(outline);
  function updateReadingContext() {
    const s = state.selected;
    readerNav.hidden = !s;
    if (!s) return;
    $("sourceFrames").hidden = s.kind !== "task";
    $("openVersions").hidden = s.kind !== "task";
    const contentType =
      s.summary_source === "subtitle-extract"
        ? "字幕原文 · 未调用模型"
        : s.summary_source === "local-template"
          ? "字幕摘录 · 尚未总结"
          : s.summary_source
            ? "AI 整理笔记"
            : s.transcript_path
              ? "字幕已取得 · 等待总结"
              : "正在准备内容";
    $("readerMetadata").textContent =
      s.kind === "material"
        ? "原始资料 · 可编辑修订"
        : `${contentType}${s.media_integrity?.duration ? " · " + timestamp(s.media_integrity.duration) : ""}`;
    $("sourceFrames").hidden =
      s.kind !== "task" || !(s.frame_grids || []).length;
  }
  $("sourceFrames").onclick = async () => {
    const s = state.selected;
    if (!s || s.kind !== "task") return;
    await openSource();
    if (state.selected?.id !== s.id) return;
    $("sourcePanel").dataset.contentMode = "frames";
    if ($("sourceTranscript")) $("sourceTranscript").open = true;
    $("sourceContent").innerHTML =
      (s.frame_grids || [])
        .map(
          (grid, i) =>
            `<figure><img loading="lazy" src="${esc(taskAsset(grid.url, s.id))}" alt="画面窗口 ${i + 1}" style="width:100%"><figcaption><button data-frame-start="${Number(grid.start) || 0}">${timestamp(grid.start)} – ${timestamp(grid.end)} · 回看视频</button></figcaption></figure>`,
        )
        .join("") ||
      '<p class="muted">当前笔记没有画面网格。可在创建或重新整理时启用画面处理。</p>';
    $("sourceContent")
      .querySelectorAll("[data-frame-start]")
      .forEach(
        (button) =>
          (button.onclick = () => {
            $("player").currentTime = Number(button.dataset.frameStart);
            $("player")
              .play()
              .catch(() => {});
          }),
      );
  };
  $("focusReading").onclick = () => {
    const on = document.body.classList.toggle("focus-reading");
    $("focusReading").textContent = on ? "退出专注" : "专注阅读";
  };
  $("openOutline").onclick = () => {
    const headings = [...$("document").querySelectorAll("h2,h3,h4")];
    outline.innerHTML =
      '<header><h2>笔记结构</h2><button aria-label="关闭">×</button></header><p class="muted">选择章节，直接跳到笔记对应位置。</p><nav class="outline-tree">' +
      headings
        .map(
          (h, i) =>
            `<button data-heading="${i}" style="--level:${Number(h.tagName.slice(1)) - 2}">${esc(h.textContent)}</button>`,
        )
        .join("") +
      (headings.length
        ? ""
        : '<p class="muted">当前内容还没有章节标题。完成总结后，这里会列出正文目录。</p>') +
      "</nav>";
    outline.querySelector("header button").onclick = () => outline.close();
    outline.querySelectorAll("[data-heading]").forEach(
      (b) =>
        (b.onclick = () => {
          outline.close();
          headings[Number(b.dataset.heading)].scrollIntoView({
            behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
              ? "instant"
              : "smooth",
            block: "start",
          });
        }),
    );
    outline.showModal();
  };
  installSummaryVersions({ state, openItem, notice });
  const home = $("welcome");
  home.innerHTML = `<div class="home-heading"><div><h1>今天，想学些什么？</h1><p>从一段视频或一份资料开始。</p></div><button id="homePreferences">生成设置 ${icons.settings}</button></div><div class="home-grid"><section class="home-create"><h2>开始一份新笔记</h2><form id="homeUrlForm"><label for="homeUrl">视频链接 / Bilibili BV 号</label><div class="home-input"><input id="homeUrl" placeholder="粘贴视频地址，或输入 BV 号" required><button class="primary">识别链接</button></div></form><div class="home-source-actions"><button id="homeLocal">本地视频 / 文档</button><button id="homeBrowser">浏览器当前视频</button></div><div class="home-modes"><button data-home-depth="brief">快速浏览<small>重点与时间轴</small></button><button data-home-depth="standard" class="active">标准学习<small>解释、例子与来源</small></button><button data-home-depth="deep">深入整理<small>推导与操作细节</small></button></div><p id="homeModeSummary" class="muted">当前：标准学习 · 可在生成前调整风格和处理选项</p></section><details class="home-runtime" id="runtimeDetails"><summary><strong>工作环境</strong><br><small id="runtimeSummary">检查中…</small></summary><dl><dt>文字模型</dt><dd id="runtimeModel">读取中…</dd><dt>转写</dt><dd id="runtimeAsr">读取中…</dd><dt>浏览器连接</dt><dd id="runtimeExtension">读取中…</dd><dt>处理中</dt><dd id="runtimeQueue">0 个任务</dd></dl><button id="runtimeSettings">管理模型与处理设置</button></details></div><section class="home-recent"><header><h2>最近的笔记</h2><span id="homeLibraryCount"></span></header><div id="homeRecentList"></div></section><button id="welcomeNew" hidden>新建笔记</button>`;
  $("welcomeNew").onclick = () => $("newNote").click();
  $("homeUrlForm").onsubmit = async (e) => {
    e.preventDefault();
    const button = e.submitter;
    button.disabled = true;
    try {
      const result = await api("/api/source/normalize", {
        method: "POST",
        body: JSON.stringify({ value: $("homeUrl").value }),
      });
      $("url").value = result.source.url;
      $("newNote").click();
      document.querySelector('[data-input="url"]').click();
      $("createStatus").textContent =
        "链接已识别。确认风格和处理选项后开始整理；也可以先检查媒体可用性。";
    } catch (error) {
      notice(error.message);
    } finally {
      button.disabled = false;
    }
  };
  const inspect = document.createElement("button");
  inspect.type = "button";
  inspect.id = "inspectSource";
  inspect.textContent = "检查媒体可用性";
  $("urlInput").append(inspect);
  inspect.onclick = async () => {
    inspect.disabled = true;
    const input = $("url").value.trim();
    $("createStatus").textContent = "正在检查媒体候选，尚未创建任务…";
    try {
      const result = await api("/api/media/preflight-current-page", {
        method: "POST",
        body: JSON.stringify({
          page_url: input,
          resources: [],
          cookies: [],
          probe_limit: 3,
        }),
      });
      if (input !== $("url").value.trim()) return;
      $("createStatus").textContent =
        `${result.report.message} 候选 ${result.report.candidate_count} 个，可用 ${result.report.downloadable_count} 个。`;
    } catch (error) {
      $("createStatus").textContent = error.message;
    } finally {
      inspect.disabled = false;
    }
  };
  $("homeLocal").onclick = () => {
    $("newNote").click();
    document.querySelector('[data-input="file"]').click();
  };
  $("homeBrowser").onclick = () => {
    $("newNote").click();
    document.querySelector('[data-input="browser"]').click();
  };
  $("homePreferences").onclick = () => {
    $("settings").click();
    document.querySelector('[data-settings-section="notes"]')?.click();
  };
  $("runtimeSettings").onclick = () => $("settings").click();
  home.querySelectorAll("[data-home-depth]").forEach(
    (b) =>
      (b.onclick = () => {
        $("depth").value = b.dataset.homeDepth;
        home
          .querySelectorAll("[data-home-depth]")
          .forEach((el) => el.classList.toggle("active", el === b));
        $("homeModeSummary").textContent =
          `当前：${b.firstChild.textContent} · 可在生成前调整风格和处理选项`;
      }),
  );
  function renderHome() {
    const h = state.health;
    if (!h.app_version) return;
    home.dataset.ready = "true";
    const configured = state.model.use_saved_connection
      ? Boolean(state.modelConnectionReady)
      : Boolean(
          state.key ||
            (h.llm_model_configured &&
              (!state.model.base_url ||
                state.model.base_url === h.default_llm_base_url)),
        );
    $("runtimeSummary").textContent =
      (configured ? "模型设置已保存" : "模型设置待检查") +
      " · " +
      (h.local_asr_available ? "转写组件可用" : "优先字幕");
    if (!$("runtimeDetails").dataset.initialized) {
      const saved = localStorage.getItem("learnnote.runtime.expanded");
      $("runtimeDetails").open = saved === "true";
      $("runtimeDetails").dataset.initialized = "true";
      $("runtimeDetails").addEventListener("toggle", () =>
        localStorage.setItem(
          "learnnote.runtime.expanded",
          String($("runtimeDetails").open),
        ),
      );
    }

    $("runtimeModel").textContent =
      (state.model.model || h.default_llm_model || "未选择模型") +
      (configured
        ? state.model.use_saved_connection
          ? " · 使用账号连接"
          : ""
        : state.model.use_saved_connection
          ? " · 账号连接待检查"
          : " · 尚未配置 Key");
    $("runtimeAsr").textContent = h.local_asr_available
      ? "本地转写组件可用"
      : "优先字幕 · 本地转写未就绪";
    $("runtimeExtension").textContent = state.connectionError
      ? "本机服务连接中断"
      : h.extension_connected
        ? "已连接"
        : "等待浏览器扩展";
    $("runtimeQueue").textContent =
      state.items.filter((i) =>
        ["queued", "running", "cancelling"].includes(i.status),
      ).length + " 个任务";
    $("homeLibraryCount").textContent = state.items.length + " 份内容";
    $("homeRecentList").innerHTML =
      state.items
        .slice(0, 6)
        .map(
          (item, i) =>
            `<button class="recent-note" data-recent="${i}"><span><strong>${esc(item.title)}</strong><small>${esc(item.kind === "task" ? (item.summary_source === "subtitle-extract" ? "字幕已提取" : item.summary_source === "local-template" ? "字幕已保留 · 待生成总结" : { success: "笔记已完成", failed: "需要处理", cancelled: "已停止", running: "正在整理", queued: item.awaiting_confirmation ? "等待开始" : "排队中" }[item.status] || "正在整理") : "本地资料")} · ${esc((item.updated_at || "").slice(0, 10))}</small></span></button>`,
        )
        .join("") ||
      '<p class="muted">导入内容后，最近笔记和处理状态会显示在这里。</p>';
    $("homeRecentList")
      .querySelectorAll("[data-recent]")
      .forEach(
        (b) =>
          (b.onclick = () =>
            openItem(state.items[Number(b.dataset.recent)]).catch((e) =>
              notice(e.message),
            )),
      );
    updateReadingContext();
  }
  window.addEventListener("learnnote:library", renderHome);
  window.addEventListener("learnnote:settings", renderHome);
  renderHome();
  window.LearnNoteAssistant = { open: () => toggleAssistant(true) };
  return { toggleAssistant, renderHome };
}
