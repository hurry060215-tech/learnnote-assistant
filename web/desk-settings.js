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
    updates: "更新中心",
    model: "AI 模型",
    usage: "Token 用量",
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
      $("savePreferences").hidden = key === "storage" || key === "usage" || key === "updates";
      if (key === "usage") loadUsage();
      if (key === "updates") window.LearnNoteUpdates?.refresh?.(false);
    };
  }
  panes.updates.innerHTML =
    "<p class='muted'>正式频道只从 LearnNote 官方发布源读取版本信息。下载在后台进行，只有你点击“重启并更新”时才会安装；普通服务器部署只显示版本说明，不具备本机安装能力。</p>" +
    "<div class='update-center-grid'>" +
    "<section class='update-card' aria-labelledby='updateClientHeading'><h4 id='updateClientHeading'>桌面客户端</h4><p id='updateClientVersion' class='settings-status'>当前版本：读取中…</p><p id='updateClientAvailability' class='muted' role='status'></p></section>" +
    "<section class='update-card' aria-labelledby='updateExtensionHeading'><h4 id='updateExtensionHeading'>浏览器扩展</h4><p id='updateExtensionVersion' class='settings-status'>当前版本：读取中…</p><p id='updateExtensionAvailability' class='muted' role='status'></p><div class='settings-inline-actions'><button type='button' id='downloadExtensionUpdate' hidden>下载解压版更新</button><button type='button' id='cancelExtensionUpdate' hidden>取消下载</button><button type='button' id='applyExtensionUpdate' hidden>更新并打开扩展页</button></div></section>" +
    "</div>" +
    "<label class='check'><input type='checkbox' id='updateAutoCheck' checked>启动后每 24 小时检查一次正式版</label>" +
    "<label class='check'><input type='checkbox' id='updateAutoDownload' checked>发现正式版后在后台下载完整安装包</label>" +
    "<div class='settings-inline-actions'><button type='button' id='checkUpdates'>立即检查</button><button type='button' id='downloadUpdate' hidden>后台下载</button><button type='button' id='cancelUpdate' hidden>取消下载</button><button type='button' class='primary' id='applyUpdate' hidden>重启并更新</button><a class='tool-link' id='updateReleaseLink' hidden target='_blank' rel='noreferrer'>查看版本说明 ↗</a></div>" +
    "<p id='updateDownloadStatus' class='settings-status' role='status' aria-live='polite'></p>";
  let updateStatus = null, updateDownload = null, extensionDownload = null, updatePolling = 0, updateLoading = false, applyingUpdate = false;
  async function updateAction(component, action, version) {
    const body = JSON.stringify({component, action, version});
    const intent = await api("/api/update/intent", {method:"POST", body});
    return api("/api/update/action", {method:"POST", body, headers:{"Content-Type":"application/json", "X-LearnNote-Update-Intent":intent.token}});
  }
  const httpUpdateBridge = {
    update_status: (force) => api("/api/update/status" + (force ? "?force=true" : "")),
    start_update_download: (version) => updateAction("client","download",version),
    apply_update: (version) => updateAction("client","apply",version),
    cancel_update_download: () => updateAction("client","cancel",updateDownload?.version || "0.0.0"),
    start_extension_update_download: (version) => updateAction("extension","download",version),
    apply_extension_update: (version) => updateAction("extension","apply",version),
    cancel_extension_update_download: () => updateAction("extension","cancel",extensionDownload?.version || "0.0.0"),
    set_update_preferences: (auto_check, auto_download) => api("/api/update/preferences", {method:"PUT",body:JSON.stringify({auto_check,auto_download})}),
  };
  const updateBridge = () => window.pywebview?.api || (updateStatus?.capabilities?.desktop_controller ? httpUpdateBridge : null);
  function normalizeBridgeUpdate(result) {
    const currentVersion = state.health?.app_version || "0.0.0";
    const extensionVersion = state.health?.extension_version || "";
    const versionParts = (value) => String(value || "").split(".").map(Number);
    const newer = (left, right) => {
      const a = versionParts(left), b = versionParts(right);
      return a.length === 3 && b.length === 3 && a.every(Number.isFinite) && b.every(Number.isFinite) && a.some((value, index) => value !== b[index]) && (a[0] > b[0] || (a[0] === b[0] && (a[1] > b[1] || (a[1] === b[1] && a[2] > b[2]))));
    };
    return {
      ok: Boolean(result?.ok),
      current: { client_version: currentVersion, extension_version: extensionVersion },
      latest: result?.latest_version ? { version: result.latest_version, release_url: result.release_url || "", client: { url: result.installer_url || "", sha256: result.installer_sha256 || "", installable: Boolean(result.installable) } } : null,
      client_update_available: newer(result?.latest_version, currentVersion),
      extension: { current_version: extensionVersion, compatibility: extensionVersion && extensionVersion !== currentVersion ? "version_check_pending" : "compatible", channel: "browser_store_or_managed_unpack", store_update: "browser_managed" },
      capabilities: { download: Boolean(updateBridge()?.start_update_download || updateBridge()?.download_update), apply: Boolean(updateBridge()?.apply_update || updateBridge()?.install_update) },
      download: updateDownload || { phase: "idle" },
      error: result?.message || "",
    };
  }
  function renderUpdateCenter(result) {
    updateStatus = result;
    const current = result?.current || {};
    const latest = result?.latest;
    $("updateClientVersion").textContent = "当前版本：v" + (current.client_version || "未知");
    $("updateExtensionVersion").textContent = "当前版本：" + (current.extension_version ? "v" + current.extension_version : "未连接");
    const clientAvailable = Boolean(result?.client_update_available && latest?.version);
    $("updateClientAvailability").textContent = clientAvailable
      ? "发现正式版 v" + latest.version + (latest.client?.installable ? "，安装包已通过来源与校验信息检查。" : "，当前资产暂不可自动安装。")
      : result?.ok ? "当前已是最新正式版，或当前开发版本不低于正式版。" : "暂时无法检查正式版" + (result?.error ? "：" + result.error : "");
    const ext = result?.extension || {};
    const extLatest = latest?.extension;
    const extAvailable = Boolean(result?.extension_update_available && extLatest?.available);
    $("updateExtensionAvailability").textContent = extAvailable
      ? "发现扩展 v" + latest.version + "。商店版由 Chrome / Edge 自己更新；受管理解压版可下载到固定目录。"
      : ext.compatibility === "compatible"
        ? "协议兼容。商店版由 Chrome / Edge 自己更新；受管理解压版由客户端维护固定目录。"
        : ext.current_version ? "版本信息待扩展下一次心跳确认；客户端不会仅因补丁号不同阻断使用。" : "尚未连接扩展；安装方式和商店审核状态不会影响客户端更新。";
    const bridge = updateBridge();
    const canDownload = Boolean(clientAvailable && latest?.client?.installable && result?.capabilities?.download && bridge);
    $("downloadUpdate").hidden = !canDownload || ["downloading", "cancelling", "ready"].includes(updateDownload?.phase);
    $("cancelUpdate").hidden = !["downloading", "cancelling"].includes(updateDownload?.phase);
    $("applyUpdate").hidden = !(updateDownload?.phase === "ready" && updateDownload?.path);
    const releaseUrl = latest?.page_url || latest?.release_url;
    $("updateReleaseLink").hidden = !releaseUrl;
    if (releaseUrl) $("updateReleaseLink").href = releaseUrl;
    if (updateDownload?.phase && updateDownload.phase !== "idle") {
      const done = updateDownload.downloaded_bytes || 0, total = updateDownload.total_bytes || 0;
      $("updateDownloadStatus").textContent = updateDownload.phase === "downloading"
        ? "正在后台下载 v" + updateDownload.version + "：" + (total ? done.toLocaleString() + " / " + total.toLocaleString() + " 字节（" + (updateDownload.progress || 0) + "%）" : done.toLocaleString() + " 字节")
        : updateDownload.phase === "ready" ? "下载完成并已校验。确认没有进行中的任务后，可点击“重启并更新”。"
          : updateDownload.phase === "failed" ? "下载失败：" + (updateDownload.error || "请重试")
            : updateDownload.phase === "cancelled" ? "下载已取消，原程序未改变。" : "正在取消下载…";
    }
    const canExtensionDownload = Boolean(extAvailable && extLatest?.url && extLatest?.sha256 && bridge?.start_extension_update_download);
    $("downloadExtensionUpdate").hidden = !canExtensionDownload || ["downloading", "cancelling", "ready"].includes(extensionDownload?.phase);
    $("cancelExtensionUpdate").hidden = !["downloading", "cancelling"].includes(extensionDownload?.phase);
    $("applyExtensionUpdate").hidden = !(extensionDownload?.phase === "ready" && extensionDownload?.path);
  }
  async function readUpdateStatus(force = false) {
    if (updateLoading && !force) return updateStatus;
    updateLoading = true;
    try {
      const bridge = updateBridge();
      let result;
      if (bridge?.update_status) result = await bridge.update_status(Boolean(force));
      else if (force && bridge?.check_update) result = normalizeBridgeUpdate(await bridge.check_update());
      else result = await api("/api/update/status" + (force ? "?force=true" : ""));
      updateDownload = result.download || updateDownload || { phase: "idle" };
      extensionDownload = result.extension_download || extensionDownload || { phase: "idle" };
      if (![updateDownload.phase, extensionDownload.phase].some(phase => ["downloading", "cancelling"].includes(phase))) clearInterval(updatePolling);
      if (result.preferences) {
        $("updateAutoCheck").checked = result.preferences.auto_check !== false;
        $("updateAutoDownload").checked = result.preferences.auto_download !== false;
        saved(["updates"]);
      }
      renderUpdateCenter(result);
      return result;
    } finally { updateLoading = false; }
  }
  async function startUpdateDownload() {
    const latest = updateStatus?.latest, bridge = updateBridge();
    if (!latest?.client?.installable || !bridge) return;
    try {
      updateDownload = bridge.start_update_download
        ? await bridge.start_update_download(latest.version, latest.client.url, latest.client.sha256)
        : { phase: "downloading", version: latest.version };
      renderUpdateCenter(updateStatus);
      if (!bridge.start_update_download) {
        const result = await bridge.download_update(latest.version, latest.client.url, latest.client.sha256);
        updateDownload = { phase: "ready", version: latest.version, path: result.path, progress: 100 };
        renderUpdateCenter(updateStatus);
      }
      clearInterval(updatePolling);
      updatePolling = setInterval(() => readUpdateStatus(false).catch(() => {}), 500);
    } catch (error) {
      updateDownload = { phase: "failed", error: error.message };
      renderUpdateCenter(updateStatus);
    }
  }
  async function applyPreparedUpdate() {
    if (applyingUpdate || !updateDownload?.path || !updateStatus?.latest || !updateBridge()) return;
    if (updateDirty().length || !ctx.guard()) { $("updateDownloadStatus").textContent = "请先保存未完成的编辑与设置，再进行更新。"; return; }
    const active = state.items.filter((item) => ["queued", "running", "cancelling"].includes(item.status));
    if (active.length) {
      $("updateDownloadStatus").textContent = "还有 " + active.length + " 个任务正在处理，完成或停止后再更新。";
      return;
    }
    try {
      applyingUpdate = true;
      $("applyUpdate").disabled = true;
      const bridge = updateBridge();
      const result = bridge.apply_update ? await bridge.apply_update(updateStatus.latest.version, updateDownload.path, updateStatus.latest.client.sha256) : await bridge.install_update(updateStatus.latest.version, updateDownload.path);
      if (!result?.ok) throw new Error(result?.message || "更新未启动");
      $("updateDownloadStatus").textContent = "更新已排队，客户端将在关闭后安装并重新启动。";
    } catch (error) {
      applyingUpdate = false;
      $("applyUpdate").disabled = false;
      $("updateDownloadStatus").textContent = error.message || "更新未启动，原程序未改变。";
    }
  }
  async function startExtensionUpdateDownload() {
    const latest = updateStatus?.latest, bridge = updateBridge(), asset = latest?.extension;
    if (!asset?.available || !asset.url || !asset.sha256 || !bridge?.start_extension_update_download) return;
    try {
      extensionDownload = await bridge.start_extension_update_download(latest.version, asset.url, asset.sha256);
      renderUpdateCenter(updateStatus);
      clearInterval(updatePolling);
      updatePolling = setInterval(() => readUpdateStatus(false).catch(() => {}), 500);
    } catch (error) {
      extensionDownload = { phase: "failed", error: error.message };
      renderUpdateCenter(updateStatus);
    }
  }
  async function applyPreparedExtensionUpdate() {
    const latest = updateStatus?.latest, bridge = updateBridge(), asset = latest?.extension;
    if (!extensionDownload?.path || !asset?.sha256 || !bridge?.apply_extension_update) return;
    if (updateDirty().length || !ctx.guard()) { $("updateExtensionAvailability").textContent = "请先保存未完成的编辑与设置，再进行更新。"; return; }
    const active = state.items.filter((item) => ["queued", "running", "cancelling"].includes(item.status));
    if (active.length) {
      $("updateExtensionAvailability").textContent = "还有 " + active.length + " 个任务正在处理，完成或停止后再更新扩展。";
      return;
    }
    try {
      const result = await bridge.apply_extension_update(latest.version, extensionDownload.path, asset.sha256);
      if (!result?.ok) throw new Error(result?.message || "扩展更新未启动");
      $("updateExtensionAvailability").textContent = result.message || "解压扩展已更新，请在扩展管理页重新加载。";
      if (bridge.setup_browser_extension) await bridge.setup_browser_extension(state.health?.extension_version || "");
    } catch (error) {
      $("updateExtensionAvailability").textContent = error.message || "扩展更新失败，原扩展未改变。";
    }
  }
  async function refreshUpdates(force = false) {
    try { return await readUpdateStatus(force); }
    catch (error) {
      $("updateDownloadStatus").textContent = error.message || "更新状态暂时无法读取。";
      return null;
    }
  }
  $("checkUpdates").onclick = () => refreshUpdates(true).then((result) => result?.client_update_available && result?.preferences?.auto_download !== false ? startUpdateDownload() : null);
  $("downloadUpdate").onclick = startUpdateDownload;
  $("downloadExtensionUpdate").onclick = startExtensionUpdateDownload;
  $("cancelUpdate").onclick = async () => {
    const bridge = updateBridge();
    if (bridge?.cancel_update_download) updateDownload = await bridge.cancel_update_download();
    renderUpdateCenter(updateStatus);
  };
  $("applyUpdate").onclick = applyPreparedUpdate;
  $("applyExtensionUpdate").onclick = applyPreparedExtensionUpdate;
  $("cancelExtensionUpdate").onclick = async () => {
    const bridge = updateBridge();
    if (bridge?.cancel_extension_update_download) extensionDownload = await bridge.cancel_extension_update_download();
    renderUpdateCenter(updateStatus);
  };
  for (const id of ["updateAutoCheck", "updateAutoDownload"]) $(id).onchange = async () => {
    const bridge = updateBridge();
    const payload = { auto_check: $("updateAutoCheck").checked, auto_download: $("updateAutoDownload").checked };
    try {
      if (bridge?.set_update_preferences) await bridge.set_update_preferences(payload.auto_check, payload.auto_download);
      else await api("/api/update/preferences", { method: "PUT", body: JSON.stringify(payload) });
      saved(["updates"]);
    } catch (error) { notice(error.message); }
  };
  window.LearnNoteUpdates = {
    refresh: refreshUpdates,
    startupCheck: async () => {
      const result = await refreshUpdates(false);
      const preferences = result?.preferences || {};
      if (preferences.auto_check === false) return result;
      if (preferences.last_checked_at && Date.now() / 1000 - preferences.last_checked_at < 24 * 60 * 60) return result;
      const checked = await refreshUpdates(true);
      if (checked?.client_update_available && checked.preferences?.auto_download !== false) await startUpdateDownload();
      return checked;
    },
  };
  setTimeout(() => refreshUpdates(false), 0);
  panes.usage.innerHTML += '<p class="muted">仅统计本机 LearnNote 更新后发起的模型请求。Token 使用服务商返回的实际值；未返回用量不记为零。不包含账号余额、其他应用或本地语音转写，也不推算费用。</p><button type="button" id="refreshTokenUsage">刷新用量</button><div id="tokenUsageReport" aria-live="polite"></div>';
  let usageLoading = false;
  async function loadUsage() {
    if (usageLoading) return;
    usageLoading = true;
    const target = $("tokenUsageReport");
    target.textContent = "正在读取用量…";
    try {
      const data = await api("/api/model/usage");
      const t = data.totals, n = value => Number(value).toLocaleString();
      target.innerHTML = `<h3>${n(t.total_tokens)} Token</h3><p>输入 ${n(t.input_tokens)} · 输出 ${n(t.output_tokens)}</p><p>${n(t.requests)} 次请求 · ${n(t.requests-t.measured_requests)} 次未返回用量</p><h4>最近请求</h4>`;
      if (!data.recent.length) target.insertAdjacentHTML("beforeend", '<p class="muted">还没有记录。下次生成笔记或询问助手后，可在这里查看。</p>');
      for (const item of data.recent) {
        const row = document.createElement("p");
        const purpose = {note:"笔记生成",assistant:"助手",diagnostics:"连接诊断",connection_test:"连接测试"}[item.purpose] || item.purpose;
        row.textContent = `${new Date(item.at).toLocaleString()} · ${item.model} · ${purpose} · ${item.total_tokens == null ? "未返回用量" : n(item.total_tokens)+" Token"} · ${item.status === "success" ? "完成" : "未完成"}`;
        target.append(row);
      }
    } catch { target.textContent = "用量暂时无法读取，请点击刷新重试。"; }
    finally { usageLoading = false; }
  }
  $("refreshTokenUsage").onclick = loadUsage;
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
  const routePanel = document.createElement("details");
  routePanel.className = "model-route-panel";
  routePanel.setAttribute("aria-labelledby", "modelRouteHeading");
  routePanel.innerHTML =
    '<summary id="modelRouteHeading">查看字幕与模型处理路线</summary><button type="button" id="refreshModelRoute">刷新路线</button><p id="modelRouteSummary" class="muted" role="status">正在读取字幕、模型和离线就绪度…</p><div id="modelRouteList" class="model-route-list"></div>';
  panes.model.querySelector("h3").after(routePanel);
  async function loadModelRoute() {
    const summary = $("modelRouteSummary"), list = $("modelRouteList");
    if (!summary || !list) return;
    summary.textContent = "正在读取字幕、模型和离线就绪度…";
    try {
      const route = await api("/api/model/route");
      summary.textContent = route.routes?.some(item => item.network === "required")
        ? "总结会调用你配置的模型；优先读取字幕，缺少字幕时再转写。"
        : "此路线不调用远程模型；平台字幕仍需连接视频站点获取。";
      list.innerHTML = (route.routes || []).map((item) => `<article class="model-route-item ${item.ready ? "ready" : "waiting"}"><div><strong>${esc(item.label)}</strong><span>${item.id === "platform_or_embedded_subtitles" ? "按需检测" : item.ready ? "已就绪" : "待准备"}</span></div><p>${esc(item.detail)}</p><small>${item.network === "required" ? "需要网络" : item.network === "offline_after_model_ready" ? "模型准备后可离线" : "不调用模型"}</small></article>`).join("");
      if (route.blocking_reasons?.length) {
        summary.textContent += " " + route.blocking_reasons.join(" ");
      }
    } catch (error) {
      summary.textContent = "模型路线暂时无法读取：" + (error.message || "请稍后重试");
      list.replaceChildren();
    }
  }
  $("refreshModelRoute").onclick = loadModelRoute;
  const field = (id, label, type, value, extra = "") =>
    `<label for="${id}">${label}</label><input id="${id}" type="${type}" value="${value}" ${extra}>`;
  panes.transcriber.innerHTML +=
    '<p class="muted">本地语音模型是可选项：有平台字幕时无需下载；也可以使用远程转写。只有选择本地语音识别时才需要准备模型。</p><label for="prefTranscriber">转写方式</label><select id="prefTranscriber"><option value="faster-whisper">本地 faster-whisper</option><option value="openai-compatible">OpenAI 兼容远程转写</option><option value="groq">Groq 远程转写</option></select><label for="prefWhisper">转写模型名称 / 本地规格</label><input id="prefWhisper" list="asrModels" value="small"><datalist id="asrModels"><option value="tiny"><option value="base"><option value="small"><option value="medium"><option value="large-v3"><option value="whisper-1"><option value="whisper-large-v3"></datalist><p id="asrReadiness" class="settings-status"></p><p class="muted">远程转写复用当前模型服务的地址和 Key，请确认它支持音频转写接口，并填写转写模型名称；本地 Whisper 不上传音频。</p>';
  panes.transcriber.insertAdjacentHTML("beforeend", '<details><summary>可选：准备本地语音模型</summary><p class="muted">从 Hugging Face 模型仓库下载，可在需要离线转写时准备。首次使用无需完成此步骤。</p><select id="prepareAsrModel" aria-label="要准备的本地语音模型"><option value="tiny">tiny · 体积小</option><option value="base">base</option><option value="small" selected>small · 均衡</option><option value="medium">medium</option><option value="large-v3">large-v3 · 占用较大</option></select><div class="settings-inline-actions"><button type="button" id="checkLocalAsr">检查状态</button><button type="button" id="prepareLocalAsr">下载模型</button></div><p id="localAsrDownloadStatus" role="status"></p></details>');
  let modelPreparing = false;
  async function checkLocalAsr(prepare = false) {
    if (modelPreparing) return;
    modelPreparing = true;
    const model = $("prepareAsrModel").value;
    $("localAsrDownloadStatus").textContent = prepare ? "正在提交下载请求…" : "正在检查…";
    $("prepareLocalAsr").disabled = true;
    try {
      const result = await api(`/api/local-models/${encodeURIComponent(model)}${prepare ? "/prepare" : ""}`, prepare ? {method:"POST"} : {});
      $("localAsrDownloadStatus").textContent = result.message + (result.status === "downloading" ? " 点击检查状态查看是否完成。" : "");
    } catch(error) { $("localAsrDownloadStatus").textContent = error.message; }
    finally { modelPreparing = false; $("prepareLocalAsr").disabled = false; }
  }
  $("checkLocalAsr").onclick = () => checkLocalAsr();
  $("prepareLocalAsr").onclick = () => checkLocalAsr(true);
  panes.notes.innerHTML +=
    '<p class="muted">选择适合内容的笔记风格和版式，可补充具体整理要求。</p><label for="prefStyle">笔记风格</label><select id="prefStyle">' +
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
    '<p class="muted">调整画面采样和资源用量；采样更密集时，处理时间也会增加。</p>' +
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
  panes.appearance.insertAdjacentHTML("beforeend", '<label for="prefWeight">正文字重</label><select id="prefWeight"><option value="400">常规</option><option value="500">清晰</option><option value="600">加粗</option></select>');
  const preview = document.createElement("div");
  preview.className = "settings-status";
  preview.setAttribute("aria-label", "阅读效果预览");
  preview.innerHTML =
    "<strong>阅读效果预览</strong><p>清楚的层级、适合的字号与行距，让每一份笔记更容易阅读。</p><small>改变选项即可预览；点击保存后保留。</small>";
  panes.appearance.querySelector("h3").after(preview);
  const presets = document.createElement("div");
  presets.className = "reading-preset";
  presets.innerHTML = '<button type="button" id="clearReadingPreset">清晰紧凑</button><button type="button" id="boldReadingPreset">大字加粗</button>';
  preview.after(presets);
  const appearanceGrid = document.createElement("div");
  appearanceGrid.className = "appearance-grid";
  for (const id of ["prefReaderSize", "prefWeight", "prefFont", "prefLeading", "prefWidth", "prefDensity", "prefAccent"]) {
    const field = document.createElement("div");
    field.append(panes.appearance.querySelector(`label[for="${id}"]`), $(id));
    appearanceGrid.append(field);
  }
  presets.after(appearanceGrid);

  const preset = (large) => {
    $("prefFont").value = "sans"; $("prefLeading").value = "1.65";
    $("prefReaderSize").value = large ? "18" : "17";
    $("prefWeight").value = large ? "600" : "500";
    $("prefReaderSize").dispatchEvent(new Event("change", {bubbles:true}));
  };
  $("clearReadingPreset").onclick = () => preset(false);
  $("boldReadingPreset").onclick = () => preset(true);
  const readingDefaults = {
    size: 17,
    density: "comfortable",
    font: "sans",
    width: "940",
    leading: "1.65",
    weight: "500",
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
      weight: ["400", "500", "600"],
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
    style.setProperty("--reader-weight", p.weight);
    style.setProperty("--chosen-accent", colors[p.accent]);
    style.setProperty("--chosen-accent-dark", darkColors[p.accent]);
    document.body.classList.toggle("compact-density", p.density === "compact");
    Object.assign(preview.querySelector("p").style, {
      fontFamily: fonts[p.font],
      fontSize: p.size + "px",
      lineHeight: p.leading,
      fontWeight: p.weight,
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
      prefWeight: "weight",
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
      weight: $("prefWeight").value,
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
  $("provider").onchange = () => {
    oldProviderChange();
    $("apiKey").placeholder =
      $("baseUrl").value === state.model.base_url && state.modelConnectionReady
        ? "已保存；留空继续使用，填写可替换"
        : "填写 API Key";
    $("settingsStatus").textContent =
      "切换服务后请保存连接；不会使用其他地址的 Key。";
  };
  const oldOpen = $("settings").onclick;
  $("settings").onclick = () => {
    appearance();
    fill(state.processing || pref);
    oldOpen();
    $("apiKey").placeholder = state.modelConnectionReady
      ? "已保存；留空继续使用，填写可替换"
      : "API Key";
    $("settingsStatus").textContent = state.modelConnectionMessage || "";
    saved(Object.keys(panes));
    $("preferencesStatus").textContent =
      "各分类分别保存；阅读与外观无需连接后端。";
    loadModelRoute();
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
    if ($("baseUrl").value.trim().replace(/\/$/, "") !== state.model.base_url) {
      notice("请先选择当前已保存的模型连接，再清除它。");
      return;
    }
    if (!confirm("清除当前模型连接及其保存的 Key？其他服务的凭据不会被清除。"))
      return;
    try {
      await api("/api/model/connection", { method: "DELETE" });
      state.key = "";
      state.model = { ...state.model, use_saved_connection: false };
      state.modelConnectionReady = false;
      state.modelConnectionMessage = "当前模型连接已清除。";
      localStorage.setItem("learnnote.desk.model", JSON.stringify(state.model));
      $("apiKey").value = "";
      $("apiKey").placeholder = "填写 API Key";
      $("settingsStatus").textContent = "当前连接已清除，其他服务未更改。";
      window.dispatchEvent(new CustomEvent("learnnote:settings"));
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
  loadModelRoute();
  load();
}
