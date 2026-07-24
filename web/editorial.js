(() => {
  const STAGES = ["获取视频", "检查内容", "生成字幕", "理解画面", "整理笔记"];
  const PURPOSES = {
    review: {
      title: "课堂复习",
      summary: "按知识点组织解释，保留易错点并在末尾生成复习题。",
      sections: ["课程主题", "核心知识点", "概念解释", "易错点", "复习题"],
      style: "classroom-review", template: "standard", depth: "standard"
    },
    tutorial: {
      title: "操作教程",
      summary: "跟随演示顺序记录界面变化、命令、操作步骤和排错方法。",
      sections: ["完成目标", "准备工作", "操作步骤", "命令与参数", "常见错误"],
      style: "operation-tutorial", template: "visual-handout", depth: "deep"
    },
    exam: {
      title: "考试整理",
      summary: "把定义和考点整理成便于记忆、自测和回顾的复习材料。",
      sections: ["考试范围", "核心定义", "高频考点", "记忆卡片", "练习题"],
      style: "exam-review", template: "qa", depth: "standard"
    },
    quick: {
      title: "快速摘要",
      summary: "只保留结论、关键依据和可以回到原视频核对的时间点。",
      sections: ["一句话结论", "关键要点", "重要时间轴"],
      style: "quick-summary", template: "timeline", depth: "brief"
    }
  };

  const q = selector => document.querySelector(selector);
  const qa = selector => Array.from(document.querySelectorAll(selector));
  const ui = {
    home: q("#editorialHome"), choices: q("#editorialSourceChoices"),
    urlEntry: q("#editorialUrlEntry"), localEntry: q("#editorialLocalEntry"), browserEntry: q("#editorialBrowserEntry"),
    urlInput: q("#editorialUrlInput"), inspectUrl: q("#editorialInspectUrl"), urlStatus: q("#editorialUrlStatus"),
    fileInput: q("#editorialFileInput"), dropzone: q("#editorialDropzone"), localStatus: q("#editorialLocalStatus"),
    receiveBrowser: q("#editorialReceiveBrowser"), browserStatus: q("#editorialBrowserStatus"),
    browserConnection: q("#editorialBrowserConnection"), browserWaitBar: q("#editorialBrowserWaitBar"),
    browserSetup: q("#editorialBrowserSetup"),
    confirm: q("#editorialMediaConfirm"), cover: q("#editorialMediaCover"), source: q("#editorialMediaSource"),
    title: q("#editorialConfirmTitle"), subtitle: q("#editorialMediaSubtitle"), duration: q("#editorialDuration"),
    audio: q("#editorialAudioState"), subtitles: q("#editorialSubtitleState"), visual: q("#editorialVisualState"),
    estimate: q("#editorialEstimate"), confirmStatus: q("#editorialConfirmStatus"), start: q("#editorialStartTask"),
    purposeChoices: q("#editorialPurposeChoices"), purposePreview: q("#editorialPurposePreview"),
    importTemplate: q("#editorialImportTemplate"), templateFile: q("#editorialTemplateFile"),
    customTemplateName: q("#editorialCustomTemplateName"),
    progress: q("#editorialProgress"), progressTitle: q("#editorialProgressTitle"), currentAction: q("#editorialCurrentAction"),
    progressValue: q("#editorialProgressValue"), progressBar: q("#editorialProgressBar"), progressSteps: q("#editorialProgressSteps"),
    eta: q("#editorialEta"), technicalLog: q("#editorialTechnicalLog"), failureAction: q("#editorialFailureAction"),
    openLibrary: q("#editorialOpenLibrary"), continueCard: q("#editorialContinue"),
    continueKicker: q("#editorialContinueKicker"), continueTitle: q("#editorialContinueTitle"),
    continueMeta: q("#editorialContinueMeta"), continueAction: q("#editorialContinueAction")
  };

  if (!ui.home) return;

  let draft = null;
  let localObjectUrl = "";
  let editorialTaskId = storedEditorialTaskId();
  let customPurpose = null;
  let browserWatchTimer = 0;
  let browserWatchStartedAt = 0;
  let browserWatchGeneration = 0;
  let browserPollPending = false;

  function storedEditorialTaskId() {
    try { return window.sessionStorage?.getItem("learnnote.editorialTaskId") || ""; } catch { return ""; }
  }

  function storeEditorialTaskId(value) {
    editorialTaskId = String(value || "");
    try {
      if (editorialTaskId) window.sessionStorage?.setItem("learnnote.editorialTaskId", editorialTaskId);
      else window.sessionStorage?.removeItem("learnnote.editorialTaskId");
    } catch {}
  }

  function stopBrowserWatch() {
    browserWatchGeneration += 1;
    if (browserWatchTimer) window.clearInterval(browserWatchTimer);
    browserWatchTimer = 0;
    browserPollPending = false;
  }

  function showOnly(target) {
    if (target !== ui.browserEntry) stopBrowserWatch();
    ui.home.classList.toggle("focused", target !== ui.choices);
    for (const element of [ui.choices, ui.urlEntry, ui.localEntry, ui.browserEntry, ui.confirm, ui.progress]) {
      if (element) element.hidden = element !== target;
    }
  }

  function resetHome() {
    draft = null;
    ui.confirmStatus.textContent = "";
    showOnly(ui.choices);
    renderContinueCard();
  }

  function sourceLabel(source) {
    return source === "local" ? "本地视频" : source === "browser" ? "浏览器当前页" : "视频链接";
  }

  function finiteNumber(...values) {
    for (const value of values) {
      const number = Number(value);
      if (Number.isFinite(number) && number >= 0) return number;
    }
    return null;
  }

  function displayDuration(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) return "暂未获取";
    const rounded = Math.round(seconds);
    const hours = Math.floor(rounded / 3600);
    const minutes = Math.floor((rounded % 3600) / 60);
    const remain = rounded % 60;
    return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}` : `${minutes}:${String(remain).padStart(2, "0")}`;
  }

  function displayEstimate(seconds, duration) {
    const fallback = Number.isFinite(duration) && duration > 0 ? Math.max(75, Math.round(duration * .22 + 45)) : null;
    const value = Number.isFinite(seconds) && seconds > 0 ? seconds : fallback;
    if (!value) return "正在估算";
    const minutes = Math.max(1, Math.ceil(value / 60));
    return minutes < 60 ? `约 ${minutes} 分钟` : `约 ${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`;
  }

  function valueAt(...values) {
    return values.find(value => value !== undefined && value !== null && value !== "");
  }

  function integrityObject(value = {}) {
    return value?.preflight?.handoff_integrity || value?.preflight?.media_integrity || value?.preflight?.integrity
      || value?.report?.handoff_integrity || value?.report?.media_integrity || value?.report?.integrity
      || value?.handoff_integrity || value?.media_integrity || value?.integrity || {};
  }

  function boolSignal(...values) {
    const value = valueAt(...values);
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value > 0;
    if (typeof value === "string") {
      if (/^(true|yes|present|ready|available|ok|complete|video|audio)$/i.test(value)) return true;
      if (/^(false|no|missing|absent|none|unavailable|failed)$/i.test(value)) return false;
    }
    if (Array.isArray(value)) return value.length > 0;
    return null;
  }

  function mediaDraft(source, payload = {}, extras = {}) {
    const body = payload?.preflight || payload?.report || payload || {};
    const integrity = integrityObject(payload);
    const integrityStatus = String(integrity.status || "").toLowerCase();
    const integrityChecked = ["ready", "video_only", "audio_only", "no_media"].includes(integrityStatus)
      || (!integrityStatus && [integrity.has_audio, integrity.has_video, integrity.has_subtitles].some(value => typeof value === "boolean"))
      || (integrityStatus === "invalid" && Array.isArray(integrity.blocking_reasons) && integrity.blocking_reasons.length > 0);
    const duration = finiteNumber(body.duration, body.duration_seconds, payload.duration, payload.duration_seconds, extras.duration);
    const audio = boolSignal(
      integrityChecked ? integrity.has_audio : undefined, integrity.audio_present, integrity.audio,
      body.has_audio, body.audio_present, body.audio_stream,
      extras.audio
    );
    const subtitles = boolSignal(
      integrityChecked ? integrity.has_subtitles : undefined, integrity.subtitle_present, integrity.subtitles,
      body.has_subtitles, body.subtitle_present, body.subtitle_count,
      extras.subtitles
    );
    const visual = boolSignal(
      integrityChecked ? integrity.has_video : undefined, integrity.video_present, integrity.visual,
      body.has_video, body.video_present, body.video_stream,
      extras.visual
    );
    return {
      source,
      payload,
      file: extras.file || null,
      taskId: extras.taskId || body.task_id || payload.task_id || "",
      url: extras.url || body.page_url || body.url || "",
      title: valueAt(body.title, payload.title, extras.title, extras.file?.name, "未命名视频"),
      thumbnail: valueAt(body.thumbnail_url, payload.thumbnail_url, extras.thumbnail, ""),
      duration,
      estimatedSeconds: finiteNumber(body.estimated_seconds, payload.estimated_seconds),
      audio,
      subtitles,
      visual,
      integrity,
      ready: boolSignal(body.ready, body.downloadable, payload.ready, payload.downloadable),
      message: valueAt(body.message, payload.message, "")
    };
  }

  function stateText(value, yes, no, unknown = "尚未确认") {
    return value === true ? yes : value === false ? no : unknown;
  }

  function setFact(element, value, yes, no, unknown) {
    element.textContent = stateText(value, yes, no, unknown);
    element.dataset.state = value === true ? "good" : value === false ? "bad" : "unknown";
  }

  function safeThumbnail(url) {
    if (!url) return "";
    try {
      if (typeof safeNoteMediaUrl === "function") return safeNoteMediaUrl(url);
    } catch {}
    return /^(blob:|data:image\/|https?:\/\/)/i.test(url) ? url : "";
  }

  function renderDraft(nextDraft) {
    draft = nextDraft;
    ui.source.textContent = `${sourceLabel(draft.source)} · 视频已识别`;
    ui.title.textContent = draft.title;
    ui.subtitle.textContent = draft.message || "开始前检查声音、字幕和画面是否完整。";
    ui.duration.textContent = displayDuration(draft.duration);
    setFact(ui.audio, draft.audio, "已发现", "缺少声音");
    setFact(ui.subtitles, draft.subtitles, "已发现", "未发现", "可在转写后生成");
    setFact(ui.visual, draft.visual, "已发现", "缺少画面");
    ui.estimate.textContent = displayEstimate(draft.estimatedSeconds, draft.duration);
    const thumbnail = safeThumbnail(draft.thumbnail);
    ui.cover.innerHTML = thumbnail ? `<img src="${escapeHtml(thumbnail)}" alt="视频封面">` : `<span>LN</span>`;
    const blocked = draft.audio === false || draft.visual === false;
    ui.start.disabled = blocked;
    ui.confirmStatus.textContent = blocked
      ? draft.audio === false ? "这个文件没有声音轨，补充音频或重新获取完整视频后才能生成可靠笔记。" : "没有检测到视频画面，请重新选择媒体。"
      : "";
    applyPurpose();
    renderPurposePreview();
    showOnly(ui.confirm);
  }

  function selectedPurposeKey() {
    return q('input[name="editorialPurpose"]:checked')?.value || "review";
  }

  function selectedPurpose() {
    const key = selectedPurposeKey();
    return key === "custom" ? customPurpose : PURPOSES[key];
  }

  function applyPurpose() {
    const key = selectedPurposeKey();
    const purpose = selectedPurpose();
    if (!purpose) return false;
    const style = key === "custom" ? "custom" : purpose.style;
    if (typeof els !== "undefined") {
      if (els.noteStyle) {
        if (style === "custom" && typeof ensureCustomProfileOption === "function") ensureCustomProfileOption();
        els.noteStyle.value = style;
      }
      if (els.noteTemplate) els.noteTemplate.value = purpose.template || "standard";
      if (els.summaryDepth) els.summaryDepth.value = purpose.depth || "standard";
    }
    if (key === "custom" && customPurpose && typeof appSettings !== "undefined") {
      appSettings.customNoteProfile = customPurpose;
      appSettings.noteStyle = "custom";
    }
    try {
      if (typeof refreshNoteProfilePreview === "function") refreshNoteProfilePreview();
      if (typeof storeAppSettings === "function") storeAppSettings();
    } catch {}
    return true;
  }

  function renderPurposePreview() {
    const purpose = selectedPurpose();
    if (!purpose) {
      ui.purposePreview.innerHTML = `<strong>先导入自定义模板</strong> · 支持 YAML 或 JSON，需包含 name、prompt 和 sections。`;
      return;
    }
    ui.purposePreview.innerHTML = `<strong>${escapeHtml(purpose.title || purpose.name)}</strong> · ${escapeHtml(purpose.summary || purpose.description || "按自定义结构整理")}<br>${purpose.sections.map(escapeHtml).join("　·　")}`;
  }

  function parseYaml(text) {
    const result = {};
    let listKey = "";
    let blockKey = "";
    const blockLines = [];
    const flushBlock = () => {
      if (blockKey) result[blockKey] = blockLines.splice(0).join("\n").trim();
      blockKey = "";
    };
    for (const rawLine of String(text || "").replace(/^\uFEFF/, "").split(/\r?\n/)) {
      if (blockKey && /^\s+/.test(rawLine)) {
        blockLines.push(rawLine.replace(/^\s{2,}/, ""));
        continue;
      }
      flushBlock();
      const line = rawLine.replace(/\s+#.*$/, "").trimEnd();
      if (!line.trim() || line.trimStart().startsWith("#")) continue;
      const item = line.match(/^\s*-\s+(.+)$/);
      if (item && listKey) {
        result[listKey].push(item[1].trim().replace(/^['"]|['"]$/g, ""));
        continue;
      }
      const pair = line.match(/^\s*([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
      if (!pair) throw new Error(`无法识别这一行：${line.trim()}`);
      const [, key, rawValue] = pair;
      const value = rawValue.trim();
      listKey = "";
      if (value === "|" || value === ">") {
        blockKey = key;
      } else if (!value) {
        result[key] = [];
        listKey = key;
      } else {
        result[key] = value.replace(/^['"]|['"]$/g, "");
      }
    }
    flushBlock();
    return result;
  }

  function containsAscii(bytes, marker) {
    const target = Array.from(marker, character => character.charCodeAt(0));
    outer: for (let index = 0; index <= bytes.length - target.length; index += 1) {
      for (let offset = 0; offset < target.length; offset += 1) {
        if (bytes[index + offset] !== target[offset]) continue outer;
      }
      return true;
    }
    return false;
  }

  function scanIsoBmffTrackMarkers(chunks = []) {
    let audio = false;
    let video = false;
    for (const chunk of chunks) {
      const bytes = chunk instanceof Uint8Array ? chunk : new Uint8Array(chunk || 0);
      audio ||= containsAscii(bytes, "soun");
      video ||= containsAscii(bytes, "vide");
    }
    return { audio: audio ? true : video ? false : null, video: video ? true : audio ? false : null };
  }

  async function inspectIsoBmffTracks(file) {
    if (!/\.(mp4|m4v|mov|m4s)$/i.test(file?.name || "")) return { audio: null, video: null };
    const chunkSize = 4 * 1024 * 1024;
    const chunks = [new Uint8Array(await file.slice(0, Math.min(file.size, chunkSize)).arrayBuffer())];
    if (file.size > chunkSize) chunks.push(new Uint8Array(await file.slice(Math.max(0, file.size - chunkSize)).arrayBuffer()));
    return scanIsoBmffTrackMarkers(chunks);
  }

  async function importTemplate(file) {
    if (!file) return;
    try {
      if (file.size > 64 * 1024) throw new Error("模板文件不能超过 64 KB");
      const text = await file.text();
      const raw = /^\s*[\[{]/.test(text) ? JSON.parse(text) : parseYaml(text);
      const normalized = typeof normalizeCustomNoteProfile === "function" ? normalizeCustomNoteProfile(raw) : raw;
      if (!normalized) throw new Error("模板需要 name、prompt 和至少一个 sections 条目");
      customPurpose = { ...normalized, title: normalized.name, summary: normalized.description };
      if (typeof appSettings !== "undefined") appSettings.customNoteProfile = normalized;
      ui.customTemplateName.textContent = normalized.name;
      const customInput = q('input[name="editorialPurpose"][value="custom"]');
      if (customInput) customInput.checked = true;
      applyPurpose();
      renderPurposePreview();
    } catch (error) {
      ui.confirmStatus.textContent = `模板导入失败：${error?.message || "文件格式不正确"}`;
    } finally {
      ui.templateFile.value = "";
    }
  }

  async function fallbackVideoMetadata(file) {
    if (localObjectUrl) URL.revokeObjectURL(localObjectUrl);
    const objectUrl = URL.createObjectURL(file);
    let safeObjectUrl = "";
    try {
      const parsedObjectUrl = new URL(objectUrl);
      if (parsedObjectUrl.protocol !== "blob:" || parsedObjectUrl.origin !== window.location.origin) {
        throw new TypeError("Unexpected local media URL");
      }
      safeObjectUrl = parsedObjectUrl.href;
      localObjectUrl = safeObjectUrl;
    } catch (error) {
      URL.revokeObjectURL(objectUrl);
      localObjectUrl = "";
      throw error;
    }
    return new Promise(resolve => {
      const video = document.createElement("video");
      video.preload = "metadata";
      video.muted = true;
      const finish = extras => resolve(mediaDraft("local", {}, { file, title: file.name, ...extras }));
      video.onloadedmetadata = async () => {
        const visual = Number(video.videoWidth || 0) > 0;
        const tracks = await inspectIsoBmffTracks(file).catch(() => ({ audio: null, video: null }));
        let thumbnail = "";
        try {
          const canvas = document.createElement("canvas");
          canvas.width = 640;
          canvas.height = Math.max(360, Math.round(640 * (video.videoHeight || 360) / (video.videoWidth || 640)));
          canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
          thumbnail = canvas.toDataURL("image/jpeg", .78);
        } catch {}
        finish({ duration: video.duration, visual: tracks.video ?? visual, audio: tracks.audio, subtitles: false, thumbnail });
      };
      video.onerror = () => finish({ visual: null, audio: null, subtitles: false });
      video.src = safeObjectUrl;
    });
  }

  async function inspectLocalFile(file) {
    if (!file) return;
    ui.localStatus.textContent = "正在检查视频轨道和时长...";
    ui.fileInput.disabled = true;
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(apiUrl("/api/media/preflight-local"), { method: "POST", body: form });
      if (response.ok === false) throw new Error(`preflight-local ${response.status || "unavailable"}`);
      const payload = await response.json();
      const next = mediaDraft("local", payload, { file, title: file.name });
      renderDraft(next);
    } catch {
      const next = await fallbackVideoMetadata(file);
      ui.localStatus.textContent = "已使用本机视频信息完成检查；上传将在确认后开始。";
      renderDraft(next);
    } finally {
      ui.fileInput.disabled = false;
    }
  }

  async function inspectUrl() {
    const value = ui.urlInput.value.trim();
    if (!value) { ui.urlInput.focus(); return; }
    ui.inspectUrl.disabled = true;
    ui.urlStatus.textContent = "正在识别视频信息...";
    try {
      if (typeof els !== "undefined" && els.urlInput) els.urlInput.value = value;
      const response = await fetch(apiUrl("/api/media/preflight-current-page"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page_url: value, resources: [], cookies: [], probe_limit: 3 })
      });
      const payload = await response.json().catch(() => ({}));
      if (response.ok === false) throw new Error(payload?.detail?.message || payload?.detail || payload?.message || "链接识别失败");
      const next = mediaDraft("url", payload, { url: value, title: payload.title || value });
      renderDraft(next);
    } catch (error) {
      ui.urlStatus.textContent = error?.message || "没有识别到可用视频，请检查链接或登录状态。";
    } finally {
      ui.inspectUrl.disabled = false;
    }
  }

  function currentBrowserDraft(task) {
    const integrity = task?.handoff_integrity || task?.preflight?.handoff_integrity || task?.preflight?.media_integrity || task?.preflight?.integrity || task?.media_integrity || task?.integrity || {};
    const activeVideo = task?.active_video || task?.browser_context?.active_video || {};
    const selected = task?.selected_resource || {};
    return mediaDraft("browser", { ...task, integrity }, {
      taskId: task.id,
      title: typeof displayTaskTitle === "function" ? displayTaskTitle(task) : task.title,
      duration: activeVideo.duration,
      audio: boolSignal(
        activeVideo.src_object_audio_tracks > 0 ? true : null,
        selected.audio_url ? true : null,
        task.audio_path ? true : null
      ),
      subtitles: boolSignal(integrity.has_subtitles, task.browser_subtitles?.length, task.subtitle_path, task.transcript_path),
      visual: boolSignal(activeVideo.width > 0 ? true : null, task.media_path ? true : null, activeVideo.src ? true : null),
      thumbnail: task.thumbnail_url || task.cover_url || activeVideo.poster_url
    });
  }

  function browserHandoffTask() {
    if (!Array.isArray(tasks)) return null;
    return tasks.find(item => item?.awaiting_confirmation && item?.source_type === "current_page") || null;
  }

  function setBrowserWaitProgress(value) {
    const progress = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
    if (ui.browserWaitBar) {
      ui.browserWaitBar.style.width = `${progress}%`;
      ui.browserWaitBar.parentElement?.setAttribute("aria-valuenow", String(progress));
    }
  }

  function renderBrowserConnection(health = {}) {
    const connected = Boolean(health.extension_connected);
    const appVersion = String(health.app_version || "").trim();
    const extensionVersion = String(health.extension_version || "").trim();
    const versionCurrent = !appVersion || !extensionVersion || appVersion === extensionVersion;
    if (ui.browserConnection) {
      ui.browserConnection.dataset.state = connected && versionCurrent ? "connected" : "disconnected";
      ui.browserConnection.textContent = connected
        ? versionCurrent ? `扩展已连接${extensionVersion ? ` · v${extensionVersion}` : ""}` : `扩展版本较旧 · v${extensionVersion || "-"}`
        : "扩展尚未连接";
    }
    if (ui.browserSetup) ui.browserSetup.hidden = connected && versionCurrent;
    return connected && versionCurrent;
  }

  async function receiveBrowser({ automatic = false, generation = browserWatchGeneration } = {}) {
    if (browserPollPending) return false;
    browserPollPending = true;
    ui.receiveBrowser.disabled = true;
    if (!automatic) ui.browserStatus.textContent = "正在读取扩展交接状态...";
    try {
      let health = {};
      try { health = await fetchJson(apiUrl("/api/health")); } catch {}
      if (generation !== browserWatchGeneration) return false;
      const connected = renderBrowserConnection(health);
      if (typeof loadTasks === "function") await loadTasks();
      if (generation !== browserWatchGeneration) return false;
      const task = browserHandoffTask();
      if (!task) {
        ui.browserStatus.textContent = connected
          ? "已连接。保持视频播放，在扩展里点击“发送到 LearnNote”，这里会自动出现确认页。"
          : "客户端正在运行，但扩展没有连接。重新加载扩展后，这里会自动继续。";
        return false;
      }
      setBrowserWaitProgress(100);
      storeEditorialTaskId(task.id);
      renderDraft(currentBrowserDraft(task));
      return true;
    } finally {
      ui.receiveBrowser.disabled = false;
      browserPollPending = false;
    }
  }

  function beginBrowserWatch() {
    stopBrowserWatch();
    const generation = browserWatchGeneration;
    browserWatchStartedAt = Date.now();
    setBrowserWaitProgress(7);
    ui.browserStatus.textContent = "正在等待扩展发送当前视频...";
    receiveBrowser({ automatic: true, generation });
    browserWatchTimer = window.setInterval(() => {
      const elapsed = Math.max(0, Date.now() - browserWatchStartedAt);
      setBrowserWaitProgress(Math.min(92, 7 + elapsed / 900));
      renderBrowserConnection(typeof lastHealthData === "object" ? lastHealthData : {});
      const task = browserHandoffTask();
      if (task) {
        setBrowserWaitProgress(100);
        storeEditorialTaskId(task.id);
        renderDraft(currentBrowserDraft(task));
      }
    }, 900);
  }

  function buildLocalTaskForm(localDraft, options) {
    const form = new FormData();
    const stagingToken = localDraft?.payload?.staging_token || localDraft?.payload?.preflight?.staging_token || localDraft?.payload?.report?.staging_token || "";
    if (stagingToken) form.append("staging_token", stagingToken);
    else form.append("file", localDraft?.file);
    form.append("title", localDraft?.title || localDraft?.file?.name || "本地视频");
    form.append("options", JSON.stringify(options || {}));
    return form;
  }

  async function startDeferredBrowserTask(taskId, options, requester = fetchJson) {
    return requester(apiUrl(`/api/tasks/${encodeURIComponent(taskId)}/start`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options || {})
    });
  }

  async function startTask() {
    if (!draft || !applyPurpose()) {
      ui.confirmStatus.textContent = "请先导入或选择一个可用的笔记模板。";
      return;
    }
    ui.start.disabled = true;
    ui.confirmStatus.textContent = "正在创建任务...";
    try {
      let data = null;
      if (draft.source === "local") {
        const form = buildLocalTaskForm(draft, readOptions());
        const response = await fetch(apiUrl("/api/tasks/from-local"), { method: "POST", body: form });
        data = await response.json().catch(() => ({}));
        if (response.ok === false || !data.task_id) throw new Error(apiErrorMessage(data, "本地视频上传失败。"));
      } else if (draft.source === "url") {
        const body = draft.payload?.preflight || draft.payload?.report || draft.payload || {};
        const selected = body.selected_resource || body.resource || body.best_resource || null;
        data = await fetchJson(apiUrl("/api/tasks/from-current-page"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            mode: "video", page_url: draft.url, title: draft.title, page_text: "",
            resources: selected ? [selected] : [], page_preflight_report: body,
            cookies: [], options: readOptions()
          })
        });
      } else {
        data = await startDeferredBrowserTask(draft.taskId, readOptions());
      }
      storeEditorialTaskId(data?.task_id || draft.taskId);
      if (!editorialTaskId) throw new Error("任务没有返回有效编号");
      if (typeof selectTask === "function") selectTask(editorialTaskId);
      showOnly(ui.progress);
      renderEditorialProgress();
      if (typeof loadTasks === "function") await loadTasks();
    } catch (error) {
      ui.confirmStatus.textContent = error?.message || "任务创建失败，请重试。";
      ui.start.disabled = false;
    }
  }

  function workflowStageIndex(task = {}) {
    const raw = String(task.workflow_stage || task.phase || "queued").toLowerCase();
    const explicit = {
      acquire: 0, acquiring: 0, download: 0, downloading: 0, queued: 0,
      acquire_media: 0,
      inspect: 1, integrity: 1, detecting: 1, checking: 1, processing_video: 1,
      check_content: 1,
      transcript: 2, transcribing: 2, subtitle: 2, subtitles: 2,
      generate_transcript: 2,
      vision: 3, visual: 3, frames: 3, extracting_frames: 3, understanding: 3,
      understand_visuals: 3,
      note: 4, summary: 4, summarizing: 4, compose: 4, completed: 4, compose_note: 4
    };
    if (Object.hasOwn(explicit, raw)) return explicit[raw];
    const localized = STAGES.findIndex(label => label === task.workflow_stage);
    return localized >= 0 ? localized : 0;
  }

  function etaText(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) return "正在估算";
    if (value < 60) return `${Math.max(1, Math.ceil(value))} 秒`;
    const minutes = Math.ceil(value / 60);
    return minutes < 60 ? `${minutes} 分钟` : `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`;
  }

  function friendlyTaskAction(task = {}) {
    if (task.status === "success") return "笔记已经整理完成";
    if (task.status === "failed") {
      const failureLabels = {
        no_media_found: "没有找到可下载的视频资源",
        auth_required: "登录状态已失效，请重新打开视频页",
        drm_or_encrypted: "该视频不能通过当前页面直接获取",
        download_forbidden: "视频服务器拒绝了下载请求",
        unsupported_manifest: "暂时无法合并这个视频流",
        insufficient_evidence: "字幕或画面依据不足，已停止生成",
        task_interrupted: "客户端上次处理中断，可以重新尝试"
      };
      const localized = failureLabels[String(task.error_code || "").toLowerCase()];
      const detail = String(task.error_detail || task.message || "").trim();
      return localized || (/[\u3400-\u9fff]/.test(detail) ? detail : "处理未完成，请按下方建议继续");
    }
    const raw = String(task.message || "").trim();
    const normalized = raw.toLowerCase();
    const technicalOrEnglish = !/[\u3400-\u9fff]/.test(raw)
      || /queued|saved|processing|download|transcrib|extract|summar|markdown|local upload|current page/i.test(raw);
    if (raw && !technicalOrEnglish) return raw;
    if (/queued|saved|waiting|awaiting/.test(normalized)) return "视频已接收，正在排队";
    const actions = [
      "正在获取视频文件",
      "正在核对声音、字幕和画面",
      "正在生成可核对的字幕",
      "正在提取关键画面",
      "正在整理笔记结构"
    ];
    return actions[workflowStageIndex(task)] || "正在准备任务";
  }

  function resumableTask() {
    if (!Array.isArray(tasks)) return null;
    const awaiting = tasks.find(item => item?.awaiting_confirmation && item?.source_type === "current_page");
    if (awaiting) return { task: awaiting, kind: "confirm" };
    const active = tasks.find(item => ["queued", "running", "cancelling"].includes(item?.status));
    if (active) return { task: active, kind: "progress" };
    const recent = tasks.find(item => item?.status === "success" && item?.note_path);
    return recent ? { task: recent, kind: "note" } : null;
  }

  function renderContinueCard() {
    if (!ui.continueCard) return;
    const candidate = resumableTask();
    if (!candidate || ui.choices?.hidden) {
      ui.continueCard.hidden = true;
      return;
    }
    const { task, kind } = candidate;
    ui.continueCard.hidden = false;
    ui.continueKicker.textContent = kind === "confirm" ? "浏览器已发送" : kind === "progress" ? "任务仍在处理" : "最近完成";
    ui.continueTitle.textContent = typeof displayTaskTitle === "function" ? displayTaskTitle(task) : task.title || "未命名视频";
    ui.continueMeta.textContent = kind === "confirm"
      ? "确认声音、字幕和画面后再开始"
      : kind === "progress" ? `${friendlyTaskAction(task)} · ${Number(task.progress || 0)}%` : "笔记、字幕和画面索引已准备好";
    ui.continueAction.textContent = kind === "confirm" ? "确认视频" : kind === "progress" ? "查看进度" : "打开笔记";
    ui.continueAction.onclick = () => {
      storeEditorialTaskId(task.id);
      if (kind === "confirm") renderDraft(currentBrowserDraft(task));
      else if (kind === "progress") { showOnly(ui.progress); renderEditorialProgress(); }
      else openTask(task);
    };
  }

  function technicalSummary(task) {
    const coverage = task.evidence_coverage || {};
    const attempts = Array.isArray(task.download_attempts) ? task.download_attempts : [];
    return [
      `任务：${task.id || "-"}`,
      `状态：${task.status || "-"}`,
      `阶段：${task.workflow_stage || task.phase || "-"}`,
      `进度：${Number(task.progress || 0)}%`,
      `媒体：${task.media_path || "尚未生成"}`,
      `字幕：${task.subtitle_path || task.transcript_path || "尚未生成"}`,
      `证据覆盖：${Object.keys(coverage).length ? JSON.stringify(coverage, null, 2) : "后端暂未提供"}`,
      `下载尝试：${attempts.length}`,
      task.error_code ? `错误代码：${task.error_code}` : "",
      task.error_detail ? `错误详情：${task.error_detail}` : ""
    ].filter(Boolean).join("\n");
  }

  function primaryFailureLabel(task) {
    if (task.source_type === "current_page" && !task.media_path) return "改用本地视频";
    return "重新尝试";
  }

  async function runPrimaryRecovery(task) {
    if (task.source_type === "current_page" && !task.media_path) {
      showOnly(ui.localEntry);
      ui.fileInput.click();
      return;
    }
    try {
      const data = await fetchJson(apiUrl(`/api/tasks/${encodeURIComponent(task.id)}/retry`), { method: "POST" });
      storeEditorialTaskId(data.task_id || task.id);
      await loadTasks();
    } catch (error) {
      ui.currentAction.textContent = error?.message || "重试失败，请查看技术日志。";
    }
  }

  function openTask(task) {
    if (!task?.id) return;
    if (typeof selectTask === "function") selectTask(task.id);
    if (typeof showAppView === "function") showAppView("notes");
    if (typeof renderTasks === "function") renderTasks();
    if (typeof renderDetail === "function") renderDetail();
  }

  function renderEditorialProgress() {
    if (!editorialTaskId || !Array.isArray(tasks)) return;
    const task = tasks.find(item => item.id === editorialTaskId);
    if (!task) return;
    const progress = Math.max(0, Math.min(100, Number(task.progress || 0)));
    const stageIndex = workflowStageIndex(task);
    ui.progressTitle.textContent = typeof displayTaskTitle === "function" ? displayTaskTitle(task) : task.title || "处理视频内容";
    ui.currentAction.textContent = friendlyTaskAction(task);
    ui.progressValue.textContent = `${progress}%`;
    ui.progressBar.style.width = `${progress}%`;
    ui.progressBar.parentElement?.setAttribute("aria-valuenow", String(progress));
    ui.progressSteps.innerHTML = STAGES.map((label, index) => `<li class="${task.status === "success" || index < stageIndex ? "done" : index === stageIndex ? "active" : ""}">${label}</li>`).join("");
    ui.eta.textContent = task.status === "success" ? "已完成" : etaText(task.eta_seconds);
    ui.technicalLog.textContent = technicalSummary(task);
    ui.failureAction.hidden = !["failed", "success"].includes(task.status);
    if (task.status === "failed") {
      ui.failureAction.innerHTML = `<p>${escapeHtml(task.error_detail || task.message || "本次处理未完成。")}</p><button type="button">${escapeHtml(primaryFailureLabel(task))}</button>`;
      ui.failureAction.querySelector("button").onclick = () => runPrimaryRecovery(task);
    } else if (task.status === "success") {
      ui.failureAction.innerHTML = `<p>笔记、字幕和画面索引已经准备好。</p><button type="button">打开笔记</button>`;
      ui.failureAction.querySelector("button").onclick = () => openTask(task);
    }
  }

  qa("[data-editorial-source]").forEach(button => button.addEventListener("click", () => {
    const source = button.dataset.editorialSource;
    if (typeof setSource === "function") setSource(source);
    showOnly(source === "url" ? ui.urlEntry : source === "local" ? ui.localEntry : ui.browserEntry);
    if (source === "url") window.setTimeout(() => ui.urlInput.focus(), 0);
    if (source === "browser") beginBrowserWatch();
  }));
  qa("[data-editorial-back]").forEach(button => button.addEventListener("click", resetHome));
  ui.inspectUrl.addEventListener("click", inspectUrl);
  ui.urlInput.addEventListener("keydown", event => { if (event.key === "Enter") inspectUrl(); });
  ui.receiveBrowser.addEventListener("click", receiveBrowser);
  ui.browserSetup?.addEventListener("click", () => {
    stopBrowserWatch();
    if (typeof showAppView === "function") showAppView("settings");
    if (typeof showSettingsPane === "function") showSettingsPane("connection");
  });
  ui.fileInput.addEventListener("change", () => inspectLocalFile(ui.fileInput.files?.[0]));
  for (const eventName of ["dragenter", "dragover"]) ui.dropzone.addEventListener(eventName, event => { event.preventDefault(); ui.dropzone.classList.add("dragover"); });
  for (const eventName of ["dragleave", "drop"]) ui.dropzone.addEventListener(eventName, event => { event.preventDefault(); ui.dropzone.classList.remove("dragover"); });
  ui.dropzone.addEventListener("drop", event => inspectLocalFile(event.dataTransfer?.files?.[0]));
  ui.purposeChoices.addEventListener("change", () => { applyPurpose(); renderPurposePreview(); });
  ui.importTemplate.addEventListener("click", () => ui.templateFile.click());
  ui.templateFile.addEventListener("change", () => importTemplate(ui.templateFile.files?.[0]));
  ui.start.addEventListener("click", startTask);
  ui.openLibrary.addEventListener("click", () => { if (typeof showAppView === "function") showAppView("notes"); });

  const originalRenderTasks = typeof renderTasks === "function" ? renderTasks : null;
  if (originalRenderTasks) {
    renderTasks = function editorialRenderTasks(...args) {
      const result = originalRenderTasks.apply(this, args);
      const remembered = tasks.find(item => item.id === editorialTaskId);
      if (remembered && ["queued", "running", "cancelling"].includes(remembered.status) && !ui.choices.hidden) {
        showOnly(ui.progress);
      }
      renderEditorialProgress();
      renderContinueCard();
      return result;
    };
  }

  const savedCustom = typeof appSettings !== "undefined" ? appSettings.customNoteProfile : null;
  if (savedCustom) {
    customPurpose = { ...savedCustom, title: savedCustom.name, summary: savedCustom.description };
    ui.customTemplateName.textContent = savedCustom.name;
  }
  window.LearnNoteEditorial = Object.freeze({
    stages: [...STAGES],
    purposes: PURPOSES,
    mediaDraft,
    workflowStageIndex,
    parseYaml,
    scanIsoBmffTrackMarkers,
    buildLocalTaskForm,
    startDeferredBrowserTask,
    applyPurpose,
    currentBrowserDraft,
    friendlyTaskAction,
    resumableTask,
    displayDuration,
    displayEstimate
  });
  renderPurposePreview();
  showOnly(ui.choices);
})();
