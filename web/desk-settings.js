import { api, escapeHtml as esc } from "/web/desk-api.js";
export function installSettings(ctx) {
  const { state, notice, loadKey } = ctx,
    $ = (id) => document.getElementById(id),
    dialog = $("settingsDialog"),
    form = $("settingsForm");
  dialog.classList.add("settings-workbench");
  const header = form.querySelector("header");
  header.querySelector("h2").textContent = "工作台设置";
  const modelNodes = [...form.children].filter(
    (n) => n !== header && n.tagName !== "DETAILS",
  );
  const nativeTools = form.querySelector("details");
  const body = document.createElement("div");
  body.className = "settings-body";
  body.innerHTML =
    '<nav class="settings-sections" aria-label="设置分类"></nav><div class="settings-content"></div>';
  form.append(body);
  const nav = body.querySelector("nav"),
    content = body.querySelector(".settings-content");
  const labels = {
    model: "AI 模型",
    transcriber: "字幕与转写",
    notes: "笔记与模板",
    processing: "视频与资源",
    appearance: "阅读与外观",
    storage: "存储与连接",
  };
  const panes = {};
  for (const [key, label] of Object.entries(labels)) {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.settingsSection = key;
    b.textContent = label;
    b.setAttribute("aria-pressed", String(key === "model"));
    nav.append(b);
    const p = document.createElement("section");
    p.dataset.settingsPage = key;
    p.hidden = key !== "model";
    p.innerHTML = `<h3>${label}</h3>`;
    content.append(p);
    panes[key] = p;
    b.onclick = () => {
      for (const [k, pane] of Object.entries(panes)) pane.hidden = k !== key;
      nav
        .querySelectorAll("button")
        .forEach((btn) => btn.setAttribute("aria-pressed", String(btn === b)));
      content.scrollTop = 0;
      b.scrollIntoView({ block: "nearest", inline: "nearest" });
      $("savePreferences").textContent =
        key === "model"
          ? "保存模型连接"
          : key === "appearance"
            ? "保存阅读与外观"
            : "保存处理设置";
      $("savePreferences").hidden = key === "storage";
    };
  }
  modelNodes.forEach((n) => panes.model.append(n));
  const oldModelSave = panes.model.querySelector("footer button.primary");
  if (oldModelSave) oldModelSave.hidden = true;
  panes.storage.append(nativeTools);
  const modelActions = document.createElement("div");
  modelActions.className = "settings-inline-actions";
  modelActions.innerHTML =
    '<button type="button" id="discoverModelList">发现模型</button><button type="button" id="providerConsole">获取 API Key</button><button type="button" id="forgetModelKey">清除已保存 Key</button><datalist id="availableModels"></datalist>';
  $("model").setAttribute("list", "availableModels");
  $("settingsStatus").before(modelActions);
  const field = (id, label, type, value, extra = "") =>
    `<label for="${id}">${label}</label><input id="${id}" type="${type}" value="${value}" ${extra}>`;
  panes.transcriber.innerHTML +=
    '<p class="muted">优先复用平台或内嵌字幕；缺少字幕时按这里的设置转写。大模型首次使用可能需要下载权重。</p><label for="prefTranscriber">转写方式</label><select id="prefTranscriber"><option value="faster-whisper">本地 faster-whisper</option><option value="openai-compatible">OpenAI 兼容远程转写</option><option value="groq">Groq 远程转写</option></select><label for="prefWhisper">转写模型名称 / 本地规格</label><input id="prefWhisper" list="asrModels" value="small"><datalist id="asrModels"><option value="tiny"><option value="base"><option value="small"><option value="medium"><option value="large-v3"><option value="whisper-1"><option value="whisper-large-v3"></datalist><p id="asrReadiness" class="settings-status"></p><p class="muted">远程转写复用当前模型服务的地址和 Key，请确认它支持音频转写接口，并填写转写模型名称；本地 Whisper 不上传音频。</p>';
  panes.notes.innerHTML +=
    '<p class="muted">风格控制内容组织，格式控制呈现方式。保留全部配置入口，不用单个“深度”代替它们。</p><label for="prefStyle">笔记风格</label><select id="prefStyle">' +
    Object.entries({
      study: "学习笔记",
      lecture: "课程讲义",
      concise: "重点速记",
      exam: "考点复习",
      concept: "概念精讲",
      code: "代码教程",
      academic: "论文导读",
      language: "语言学习",
      custom: "自定义",
    })
      .map(([v, t]) => `<option value="${v}">${t}</option>`)
      .join("") +
    '</select><label for="prefTemplate">笔记格式</label><select id="prefTemplate">' +
    Object.entries({
      standard: "内容结构化",
      timeline: "时间轴",
      cornell: "康奈尔笔记",
      qa: "问答复习",
      "visual-handout": "图文讲义",
      mindmap: "层级导图",
      flashcards: "记忆卡片",
      "formula-sheet": "公式清单",
      bilingual: "双语对照",
    })
      .map(([v, t]) => `<option value="${v}">${t}</option>`)
      .join("") +
    '</select><label for="prefCustom">额外整理要求</label><textarea id="prefCustom" maxlength="4000" placeholder="例如：重点保留推导步骤，代码使用原文，不扩写课程外的知识。"></textarea><div class="settings-inline-actions"><button type="button" id="exportProfile">导出模板</button><label class="file-action">导入 JSON 模板<input id="importProfile" type="file" accept=".json,application/json"></label></div>';
  panes.processing.innerHTML +=
    '<p class="muted">保留画面密度、OCR 和资源预算的控制，处理速度与覆盖度由你权衡。</p>' +
    field("prefInterval", "抽帧间隔（秒）", "number", 20, 'min="1" max="600"') +
    field("prefFrames", "最大帧数", "number", 900, 'min="60" max="2400"') +
    field(
      "prefBudget",
      "资源预算（MB）",
      "number",
      4096,
      'min="256" max="102400"',
    ) +
    field("prefConcurrency", "视觉请求并发数", "number", 2, 'min="1" max="4"') +
    field("prefOcrLimit", "OCR 采样帧数", "number", 12, 'min="1" max="24"') +
    '<label class="check"><input type="checkbox" id="prefLowResource">低资源模式</label><p class="muted">画面理解和 OCR 是否启用，在创建任务时可直接选择。</p>';
  panes.appearance.innerHTML +=
    '<label for="prefReaderSize">正文字号</label><select id="prefReaderSize"><option value="15">15 px · 紧凑</option><option value="16">16 px</option><option value="17">17 px · 标准</option><option value="18">18 px · 较大</option><option value="20">20 px · 大字</option></select><label for="prefDensity">界面密度</label><select id="prefDensity"><option value="comfortable">标准</option><option value="compact">紧凑</option></select><label class="check"><input type="checkbox" id="prefAutoOpen">完成后自动打开笔记</label><label class="check"><input type="checkbox" id="prefNotify">任务完成时发送系统通知</label><p class="muted">系统通知需要你授予浏览器或客户端通知权限。</p>';
  panes.storage.insertAdjacentHTML(
    "afterbegin",
    '<p id="settingsDataRoot" class="settings-status"></p><div class="settings-inline-actions"><button type="button" id="openSettingsFolder">打开数据目录</button><button type="button" id="changeSettingsFolder">更改数据位置</button><button type="button" id="extensionSetupSettings">连接浏览器扩展</button></div><p id="connectionReadiness" class="muted"></p>',
  );
  const taskFormat = document.createElement("div");
  taskFormat.className = "task-format-fields";
  for (const [prefId, id, labelText] of [
    ["prefStyle", "taskStyle", "本次笔记风格"],
    ["prefTemplate", "taskTemplate", "本次笔记格式"],
  ]) {
    const label = document.createElement("label");
    label.textContent = labelText;
    label.htmlFor = id;
    const select = $(prefId).cloneNode(true);
    select.id = id;
    label.append(select);
    taskFormat.append(label);
  }
  $("generationOptions").append(taskFormat);
  window.addEventListener("learnnote:create", () => {
    $("taskStyle").value = state.processing?.note_style || "study";
    $("taskTemplate").value = state.processing?.note_template || "standard";
  });
  const footer = document.createElement("footer");
  footer.className = "settings-save-bar";
  footer.innerHTML =
    '<span id="preferencesStatus" role="status">处理参数保存在本机，任务创建时使用当前配置。</span><button type="button" id="savePreferences" class="primary">保存处理与阅读设置</button>';
  form.append(footer);
  const snapshots = new Map();
  const processingSections = ["transcriber", "notes", "processing"];
  const values = (key) =>
    JSON.stringify(
      [
        ...panes[key].querySelectorAll(
          "input:not([type=file]),select,textarea",
        ),
      ].map((input) => [
        input.id,
        input.type === "checkbox" ? input.checked : input.value,
      ]),
    );
  const dirty = (key) =>
    snapshots.has(key) && snapshots.get(key) !== values(key);
  function updateDirty() {
    const changed = Object.keys(panes).filter(dirty);
    if (changed.length) dialog.dataset.unsaved = "true";
    else delete dialog.dataset.unsaved;
    nav.querySelectorAll("button").forEach((button) => {
      const key = button.dataset.settingsSection;
      button.textContent = labels[key] + (dirty(key) ? " · 未保存" : "");
    });
    return changed;
  }
  function saved(keys) {
    keys.forEach((key) => snapshots.set(key, values(key)));
    return updateDirty();
  }
  window.LearnNoteSettings = {
    updateDirty,
    modelSaved() {
      const pending = saved(["model"]);
      if (pending.length)
        $("preferencesStatus").textContent =
          "模型连接已保存；其他分类还有未保存的修改。";
      else {
        dialog.close();
        notice("模型连接已保存");
      }
      return true;
    },
  };
  const oldSubmit = form.onsubmit;
  form.noValidate = true;
  form.onsubmit = (event) => {
    if (panes.model.hidden) {
      event.preventDefault();
      if (!panes.storage.hidden) return;
      $("savePreferences").click();
      return;
    }
    if (
      ![...panes.model.querySelectorAll("input")].every((input) =>
        input.reportValidity(),
      )
    ) {
      event.preventDefault();
      return;
    }
    return oldSubmit(event);
  };
  let pref = {};
  function fill(p, sections = processingSections) {
    pref = p;
    for (const [id, key] of Object.entries({
      prefTranscriber: "transcriber",
      prefWhisper: "whisper_model",
      prefStyle: "note_style",
      prefTemplate: "note_template",
      prefCustom: "note_profile_prompt",
      prefInterval: "frame_interval",
      prefFrames: "max_frame_count",
      prefBudget: "resource_budget_mb",
      prefConcurrency: "vision_concurrency",
      prefOcrLimit: "ocr_frame_limit",
    }))
      if (
        p[key] !== undefined &&
        sections.includes(
          $(id).closest("[data-settings-page]").dataset.settingsPage,
        )
      ) {
        const value =
          id === "prefTranscriber"
            ? {
                openai: "openai-compatible",
                "openai-compatible-asr": "openai-compatible",
                "groq-asr": "groq",
              }[p[key]] || p[key]
            : p[key];
        if (
          $(id).tagName === "SELECT" &&
          ![...$(id).options].some((option) => option.value === String(value))
        )
          $(id).add(new Option(`原有配置：${value}`, value));
        $(id).value = value;
      }
    if (sections.includes("processing"))
      $("prefLowResource").checked = Boolean(p.low_resource_mode);
  }
  panes.appearance.insertAdjacentHTML(
    "beforeend",
    '<label for="prefFont">阅读字体</label><select id="prefFont"><option value="sans">清晰黑体</option><option value="serif">书页宋体</option><option value="mono">等宽字体</option></select><label for="prefWidth">阅读宽度</label><select id="prefWidth"><option value="760">专注 · 760 px</option><option value="940">标准 · 940 px</option><option value="1120">宽屏 · 1120 px</option></select><label for="prefLeading">正文行距</label><select id="prefLeading"><option value="1.65">紧凑 · 1.65</option><option value="1.85">舒适 · 1.85</option><option value="2.1">宽松 · 2.1</option></select><label for="prefAccent">强调色</label><select id="prefAccent"><option value="neutral">石墨</option><option value="teal">青绿</option><option value="blue">靛蓝</option><option value="plum">梅紫</option></select><p class="muted">外观保存在当前浏览器或客户端；不会修改笔记内容。深浅主题可用侧栏底部按钮切换。</p>',
  );
  const preview = document.createElement("div");
  preview.className = "settings-status";
  preview.setAttribute("aria-label", "阅读效果预览");
  preview.innerHTML =
    "<strong>阅读效果预览</strong><p>清楚的层级、适合的字号与行距，让每一份笔记更容易阅读。</p><small>改变选项即可预览；点击保存后保留。</small>";
  panes.appearance.querySelector("h3").after(preview);
  const readingDefaults = {
    size: 17,
    density: "comfortable",
    font: "sans",
    width: "940",
    leading: "1.85",
    accent: "neutral",
    autoOpen: false,
    notify: false,
  };
  function normalizeReading(value) {
    const p = value && typeof value === "object" ? value : {};
    const allowed = {
      size: [15, 16, 17, 18, 20],
      density: ["comfortable", "compact"],
      font: ["sans", "serif", "mono"],
      width: ["760", "940", "1120"],
      leading: ["1.65", "1.85", "2.1"],
      accent: ["neutral", "teal", "blue", "plum"],
    };
    return Object.fromEntries(
      Object.entries(readingDefaults).map(([key, fallback]) => [
        key,
        typeof fallback === "boolean"
          ? p[key] === true
          : allowed[key].includes(
                key === "size" ? Number(p[key]) : String(p[key]),
              )
            ? key === "size"
              ? Number(p[key])
              : String(p[key])
            : fallback,
      ]),
    );
  }
  function readAppearance() {
    try {
      return normalizeReading(
        JSON.parse(
          localStorage.getItem("learnnote.reading.preferences") || "{}",
        ),
      );
    } catch {
      return { ...readingDefaults };
    }
  }
  function applyAppearance(p) {
    const fonts = {
      sans: '"Noto Sans SC", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
      serif:
        '"Noto Serif SC", "Noto Serif CJK SC", "Songti SC", "SimSun", serif',
      mono: 'Consolas, "Microsoft YaHei", monospace',
    };
    const colors = {
      neutral: "#303832",
      teal: "#087b83",
      blue: "#4057a0",
      plum: "#79516f",
    };
    const darkColors = {
      neutral: "#d5d9d6",
      teal: "#81d6d5",
      blue: "#abbdff",
      plum: "#d9aed0",
    };
    const style = document.documentElement.style;
    style.setProperty("--reader-size", p.size + "px");
    style.setProperty("--reader-font", fonts[p.font]);
    style.setProperty("--reader-width", p.width + "px");
    style.setProperty("--reader-leading", p.leading);
    style.setProperty("--chosen-accent", colors[p.accent]);
    style.setProperty("--chosen-accent-dark", darkColors[p.accent]);
    document.body.classList.toggle("compact-density", p.density === "compact");
    Object.assign(preview.querySelector("p").style, {
      fontFamily: fonts[p.font],
      fontSize: p.size + "px",
      lineHeight: p.leading,
    });
  }
  function appearance() {
    const p = readAppearance();
    for (const [id, key] of Object.entries({
      prefReaderSize: "size",
      prefDensity: "density",
      prefFont: "font",
      prefWidth: "width",
      prefLeading: "leading",
      prefAccent: "accent",
    }))
      $(id).value = p[key];
    $("prefAutoOpen").checked = p.autoOpen;
    $("prefNotify").checked = p.notify;
    applyAppearance(p);
    state.reading = p;
  }
  function collectReading() {
    return normalizeReading({
      size: Number($("prefReaderSize").value),
      density: $("prefDensity").value,
      font: $("prefFont").value,
      width: $("prefWidth").value,
      leading: $("prefLeading").value,
      accent: $("prefAccent").value,
      autoOpen: $("prefAutoOpen").checked,
      notify: $("prefNotify").checked,
    });
  }
  panes.appearance.addEventListener("input", () =>
    applyAppearance(collectReading()),
  );
  panes.appearance.addEventListener("change", () =>
    applyAppearance(collectReading()),
  );
  dialog.addEventListener("close", () => {
    appearance();
    saved(Object.keys(panes));
  });
  function collect() {
    return {
      ...pref,
      transcriber: $("prefTranscriber").value,
      whisper_model: $("prefWhisper").value,
      note_style: $("prefStyle").value,
      note_template: $("prefTemplate").value,
      note_profile_prompt: $("prefCustom").value,
      frame_interval: Number($("prefInterval").value),
      max_frame_count: Number($("prefFrames").value),
      resource_budget_mb: Number($("prefBudget").value),
      vision_concurrency: Number($("prefConcurrency").value),
      ocr_frame_limit: Number($("prefOcrLimit").value),
      low_resource_mode: $("prefLowResource").checked,
    };
  }
  let loadGeneration = 0;
  async function load() {
    const generation = ++loadGeneration;
    try {
      let result = await api("/api/preferences");
      if (state.legacyProcessing) {
        result = await api("/api/preferences", {
          method: "PUT",
          body: JSON.stringify({
            task_options: { ...result.task_options, ...state.legacyProcessing },
          }),
        });
        delete state.legacyProcessing;
      }
      if (generation !== loadGeneration) return;
      const unchanged = processingSections.filter((key) => !dirty(key));
      fill(result.task_options, unchanged);
      saved(unchanged);
      state.processing = result.task_options;
    } catch (e) {
      $("preferencesStatus").textContent = e.message;
    }
    const h = state.health || {};
    $("asrReadiness").textContent = h.local_asr_available
      ? "本地转写运行组件可用；模型权重按需下载。"
      : "本地转写组件未就绪，请检查安装与诊断。";
    $("settingsDataRoot").textContent =
      h.data_paths?.root || "数据目录由本机后端管理";
    $("connectionReadiness").textContent =
      `本机服务 ${location.origin} · 扩展${h.extension_connected ? "已连接" : "等待连接"}`;
  }
  const oldProviderChange = $("provider").onchange;
  $("provider").onchange = async () => {
    oldProviderChange();
    const provider = $("provider").value;
    if (!window.pywebview?.api?.load_model_key) return;
    try {
      const result = await window.pywebview.api.load_model_key(provider);
      if ($("provider").value !== provider) return;
      $("apiKey").value = result.api_key || "";
      $("settingsStatus").textContent = result.configured
        ? "已载入该供应商安全保存的 Key。"
        : "该供应商尚未保存 Key。";
    } catch (error) {
      $("settingsStatus").textContent = error.message;
    }
  };
  const oldOpen = $("settings").onclick;
  $("settings").onclick = () => {
    appearance();
    fill(state.processing || pref);
    oldOpen();
    saved(Object.keys(panes));
    $("preferencesStatus").textContent =
      "各分类分别保存；阅读与外观无需连接后端。";
    load();
  };
  $("savePreferences").textContent = "保存模型连接";
  $("savePreferences").onclick = async () => {
    if (!panes.model.hidden) {
      form.requestSubmit();
      return;
    }
    const button = $("savePreferences");
    button.disabled = true;
    try {
      if (!panes.appearance.hidden) {
        const reading = collectReading();
        let notificationMessage = "";
        if (reading.notify) {
          if (!window.Notification)
            notificationMessage = "当前浏览器不支持系统通知。";
          else {
            const permission =
              Notification.permission === "default"
                ? await Notification.requestPermission()
                : Notification.permission;
            if (permission !== "granted")
              notificationMessage = "系统通知未获授权；其他外观设置已保存。";
          }
          if (notificationMessage) reading.notify = false;
        }
        localStorage.setItem(
          "learnnote.reading.preferences",
          JSON.stringify(reading),
        );
        appearance();
        saved(["appearance"]);
        $("preferencesStatus").textContent =
          notificationMessage || "阅读与外观已保存在此设备，立即生效。";
      } else {
        for (const key of processingSections) {
          const invalid = [...panes[key].querySelectorAll("input")].find(
            (input) => !input.checkValidity(),
          );
          if (invalid) {
            nav.querySelector(`[data-settings-section="${key}"]`).click();
            invalid.reportValidity();
            return;
          }
        }
        const submitted = collect();
        const submittedValues = Object.fromEntries(
          processingSections.map((key) => [key, values(key)]),
        );
        const result = await api("/api/preferences", {
          method: "PUT",
          body: JSON.stringify({ task_options: submitted }),
        });
        state.processing = result.task_options;
        const unchanged = processingSections.filter(
          (key) => values(key) === submittedValues[key],
        );
        fill(result.task_options, unchanged);
        saved(unchanged);
        $("preferencesStatus").textContent =
          "处理设置已保存，新任务将使用这些参数。";
      }
      if (updateDirty().length)
        $("preferencesStatus").textContent += " 其他分类还有未保存的修改。";
      window.dispatchEvent(new CustomEvent("learnnote:settings"));
    } catch (e) {
      $("preferencesStatus").textContent = "未能保存：" + e.message;
    } finally {
      button.disabled = false;
    }
  };
  $("discoverModelList").onclick = async () => {
    const b = $("discoverModelList");
    b.disabled = true;
    try {
      const r = await api("/api/model/setup/check", {
        method: "POST",
        body: JSON.stringify({
          provider: $("provider").value,
          base_url: $("baseUrl").value,
          model: $("model").value || "auto",
          api_key: $("apiKey").value,
          use_saved_connection:
            $("provider").value === "openrouter" &&
            Boolean(state.model.use_saved_connection) &&
            $("baseUrl").value.trim() === state.model.base_url &&
            !$("apiKey").value.trim(),
          mode: "models",
        }),
      });
      $("availableModels").replaceChildren(
        ...(r.models || []).map((value) =>
          Object.assign(document.createElement("option"), { value }),
        ),
      );
      $("settingsStatus").textContent =
        r.message || `发现 ${(r.models || []).length} 个模型`;
    } catch (e) {
      $("settingsStatus").textContent = e.message;
    } finally {
      b.disabled = false;
    }
  };
  const consoles = {
    deepseek: "https://platform.deepseek.com/api_keys",
    kimi: "https://platform.kimi.com/console/api-keys",
    groq: "https://console.groq.com/keys",
    gemini: "https://aistudio.google.com/app/apikey",
    dashscope: "https://bailian.console.aliyun.com/?apiKey=1",
    xiaomi: "https://platform.xiaomimimo.com/",
    zhipu: "https://open.bigmodel.cn/usercenter/apikeys",
    doubao: "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
    minimax: "https://platform.minimaxi.com/console/access?tab=api-keys",
    qianfan:
      "https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application",
    openai: "https://platform.openai.com/api-keys",
  };
  $("providerConsole").onclick = () => {
    const url = consoles[$("provider").value];
    if (url) window.open(url, "_blank", "noopener,noreferrer");
    else
      notice("请在当前模型服务提供商的控制台管理 Key；本机服务可能无需 Key。");
  };
  $("forgetModelKey").onclick = async () => {
    if (!confirm("清除当前供应商保存的 API Key？")) return;
    try {
      if (window.pywebview?.api?.delete_model_key)
        await window.pywebview.api.delete_model_key($("provider").value);
      state.key = "";
      $("apiKey").value = "";
      $("settingsStatus").textContent =
        "已清除保存的 Key；重启客户端可清除运行时缓存的默认凭据。";
    } catch (e) {
      notice(e.message);
    }
  };
  $("openSettingsFolder").onclick = () =>
    $("openSettingsFolder") && window.pywebview?.api?.open_data_folder
      ? window.pywebview.api.open_data_folder()
      : notice("浏览器模式请按上方路径打开数据目录。");
  $("changeSettingsFolder").onclick = async () => {
    if (!window.pywebview?.api?.choose_data_directory) {
      notice("更改数据位置请使用桌面客户端。");
      return;
    }
    try {
      const r = await window.pywebview.api.choose_data_directory(true);
      if (r.cancelled) return;
      $("settingsDataRoot").textContent =
        r.message || r.path || "未更改数据位置";
      if (r.ok && !r.unchanged)
        notice("选择的数据目录准备好后，重启客户端生效。");
    } catch (e) {
      notice(e.message);
    }
  };
  $("extensionSetupSettings").onclick = () => $("setupExtension")?.click();
  $("exportProfile").onclick = () => {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(collect(), null, 2)], {
        type: "application/json",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "learnnote-note-profile.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  $("importProfile").onchange = async () => {
    try {
      const file = $("importProfile").files[0];
      if (!file) return;
      if (file.size > 64000) throw new Error("模板文件过大。");
      const data = JSON.parse(await file.text());
      const allowed = Object.keys(collect());
      fill({
        ...pref,
        ...Object.fromEntries(
          Object.entries(data).filter(([k]) => allowed.includes(k)),
        ),
      });
      updateDirty();
      $("preferencesStatus").textContent = "模板已载入，点击保存后生效。";
    } catch (e) {
      $("preferencesStatus").textContent = e.message;
    }
  };
  // Apply local appearance before waiting for the backend.
  appearance();
  saved(Object.keys(panes));
  load();
}
