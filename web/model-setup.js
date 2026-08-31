(() => {
  "use strict";

  const QUICK_PROVIDERS = ["kimi", "openai", "dashscope", "deepseek", "groq", "gemini"];
  const PROVIDER_KEY_URLS = Object.freeze({
    openai: "https://platform.openai.com/api-keys",
    groq: "https://console.groq.com/keys",
    gemini: "https://aistudio.google.com/app/apikey",
    dashscope: "https://bailian.console.aliyun.com/?apiKey=1",
    deepseek: "https://platform.deepseek.com/api_keys",
    kimi: "https://platform.kimi.com/console/api-keys",
    xiaomi: "https://platform.xiaomimimo.com/",
    zhipu: "https://open.bigmodel.cn/usercenter/apikeys",
    doubao: "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
    minimax: "https://platform.minimaxi.com/console/access?tab=api-keys",
    qianfan: "https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application"
  });

  const ui = {
    guide: document.querySelector("#modelSetupGuide"),
    state: document.querySelector("#modelSetupState"),
    status: document.querySelector("#modelSetupStatus"),
    providerSummary: document.querySelector("#modelSetupProviderSummary"),
    quickChoices: document.querySelector("#modelProviderQuickChoices"),
    openProvider: document.querySelector("#openModelProviderButton"),
    discover: document.querySelector("#discoverModelsButton"),
    test: document.querySelector("#testModelConnectionButton"),
    finish: document.querySelector("#finishModelSetupButton"),
    modelOptions: document.querySelector("#availableModelOptions")
  };
  if (!ui.guide || typeof els === "undefined") return;

  let returnContext = { view: "workspace", assistantOpen: false };
  let verifiedFingerprint = "";
  let assistantObserverBusy = false;

  function providerKey() {
    return els.llmProvider?.value || "custom";
  }

  function activePreset() {
    return modelProviderPresets?.[providerKey()] || null;
  }

  function configuredKey() {
    const inputKey = els.llmApiKey?.value?.trim() || "";
    if (inputKey) return inputKey;
    return desktopCredentialProvider === providerKey() ? desktopCredentialKey : "";
  }

  function connectionFingerprint() {
    return [providerKey(), els.llmBaseUrl?.value?.trim(), els.llmModel?.value?.trim(), configuredKey() ? "key" : "no-key"].join("|");
  }

  function setState(state, label, message = "", kind = "") {
    ui.state.dataset.state = state;
    ui.state.textContent = label;
    if (message) ui.status.textContent = message;
    ui.status.classList.toggle("success", kind === "success");
    ui.status.classList.toggle("error", kind === "error");
  }

  function renderQuickChoices() {
    const buttons = QUICK_PROVIDERS.filter(key => modelProviderPresets?.[key]).map(key => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.quickModelProvider = key;
      button.textContent = modelProviderLabel(key);
      return button;
    });
    ui.quickChoices.replaceChildren(...buttons);
    syncProviderUi();
  }

  function syncProviderUi() {
    const key = providerKey();
    const preset = activePreset();
    ui.quickChoices.querySelectorAll("[data-quick-model-provider]").forEach(button => {
      button.classList.toggle("selected", button.dataset.quickModelProvider === key);
      button.setAttribute("aria-pressed", String(button.dataset.quickModelProvider === key));
    });
    ui.providerSummary.textContent = preset
      ? `${modelProviderLabel(key)} · ${providerCapabilitySummary(preset)}`
      : "手动填写兼容端点与模型";
    const keyUrl = PROVIDER_KEY_URLS[key] || "";
    ui.openProvider.disabled = !keyUrl;
    ui.openProvider.textContent = keyUrl ? `去 ${modelProviderLabel(key)} 获取 Key` : "手动配置没有官方入口";
    if (verifiedFingerprint === connectionFingerprint()) {
      setState("ready", "验证通过");
    } else if (configuredKey()) {
      setState("idle", "待验证", `${modelProviderLabel(key)} 的 Key 已就绪，请运行一次短对话验证。`);
    } else {
      setState("idle", "需要 Key", `已选择 ${modelProviderLabel(key)}。下一步获取或填写 API Key。`);
    }
  }

  async function selectProvider(key) {
    if (!modelProviderPresets?.[key] || !els.llmProvider) return;
    els.llmProvider.value = key;
    applyModelProviderPreset(true);
    saveModelSettings();
    await loadDesktopCredential();
    verifiedFingerprint = "";
    syncProviderUi();
    window.setTimeout(() => els.llmApiKey?.focus(), 60);
  }

  function rememberReturnContext(reason = "") {
    const currentView = document.body?.dataset?.appView || "workspace";
    returnContext = {
      view: currentView === "settings" ? "workspace" : currentView,
      assistantOpen: Boolean(document.body?.classList?.contains("assistant-open")),
      reason
    };
  }

  async function open({ provider = "", reason = "manual" } = {}) {
    rememberReturnContext(reason);
    if (typeof closeOnboarding === "function" && !document.querySelector("#onboardingOverlay")?.hidden) closeOnboarding(false);
    appSettings.advancedSettings = true;
    applyAppSettings();
    showAppView("settings");
    showSettingsPane("model");
    if (provider && modelProviderPresets?.[provider]) await selectProvider(provider);
    else await loadDesktopCredential();
    syncProviderUi();
    window.setTimeout(() => {
      ui.guide.scrollIntoView({ behavior: "smooth", block: "start" });
      if (!configuredKey()) els.llmApiKey?.focus();
    }, 80);
  }

  async function openProviderConsole() {
    const key = providerKey();
    const url = PROVIDER_KEY_URLS[key] || "";
    if (!url) return;
    const api = desktopApi();
    try {
      if (api?.open_model_provider) await api.open_model_provider(key);
      else window.open(url, "_blank", "noopener,noreferrer");
      setState("idle", configuredKey() ? "待验证" : "等待填写", `已打开 ${modelProviderLabel(key)} 官方控制台。创建 Key 后回到这里粘贴。`);
    } catch {
      setState("failed", "打开失败", "无法打开官方控制台，请检查系统默认浏览器。", "error");
    }
  }

  function requestPayload(mode = "chat") {
    return {
      provider: providerKey(),
      base_url: els.llmBaseUrl?.value?.trim() || "",
      model: els.llmModel?.value?.trim() || "",
      api_key: configuredKey(),
      mode
    };
  }

  async function runCheck(mode = "chat") {
    const payload = requestPayload(mode);
    if (!payload.base_url || !payload.model) {
      setState("failed", "信息不完整", "请先填写 Base URL 和模型名称。", "error");
      return null;
    }
    if (!payload.api_key && !/^http:\/\/(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?(?:\/|$)/i.test(payload.base_url)) {
      setState("failed", "缺少 Key", "请先粘贴 API Key，或者选择已安全保存 Key 的供应商。", "error");
      els.llmApiKey?.focus();
      return null;
    }
    for (const button of [ui.test, ui.discover, ui.finish]) button.disabled = true;
    setState("testing", mode === "models" ? "正在发现" : "正在验证", mode === "models" ? "正在读取供应商模型列表…" : "正在发送一条不含学习资料的短测试消息…");
    try {
      const response = await fetch(apiUrl("/api/model/setup/check"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result?.detail?.message || result?.detail || result?.message || "模型测试失败");
      if (!result.ok) {
        setState("failed", "验证失败", result.message || "请检查 Key、模型和账户权限。", "error");
        return result;
      }
      if (mode === "models") {
        const models = Array.isArray(result.models) ? result.models.slice(0, 80) : [];
        ui.modelOptions.replaceChildren(...models.map(id => Object.assign(document.createElement("option"), { value: id })));
        if (models.length && !models.includes(els.llmModel.value.trim())) {
          const recommended = activePreset()?.model || "";
          els.llmModel.value = models.includes(recommended) ? recommended : models[0];
          saveModelSettings();
        }
        setState("idle", "已发现模型", `${result.message} 已把可用名称加入模型输入框。`, "success");
      } else {
        verifiedFingerprint = connectionFingerprint();
        const visual = result.supports_vision ? "支持画面理解" : "文本模型";
        setState("ready", "验证通过", `${result.provider_name || modelProviderLabel(providerKey())} · ${result.model} · ${visual} · ${result.latency_ms} ms`, "success");
      }
      return result;
    } catch (error) {
      setState("failed", "验证失败", error?.message || "无法连接本机验证接口。", "error");
      return null;
    } finally {
      for (const button of [ui.test, ui.discover, ui.finish]) button.disabled = false;
    }
  }

  async function saveCredentialIfNeeded() {
    const key = els.llmApiKey?.value?.trim() || "";
    const api = desktopApi();
    if (!key || !api?.save_model_key) return true;
    await api.save_model_key(providerKey(), key);
    desktopCredentialKey = key;
    desktopCredentialProvider = providerKey();
    els.llmApiKey.value = "";
    els.llmApiKey.placeholder = "已安全保存；输入新 Key 可替换";
    if (els.nativeCredentialStatus) els.nativeCredentialStatus.textContent = `${modelProviderLabel(providerKey())} 的 Key 已安全保存`;
    return true;
  }

  async function finish() {
    const result = await runCheck("chat");
    if (!result?.ok) return;
    try {
      await saveCredentialIfNeeded();
      saveModelSettings();
      updateOnboardingStatus();
      updateHealthVisionStatus();
      updateStartupReadiness();
      const target = ["workspace", "notes", "study"].includes(returnContext.view) ? returnContext.view : "workspace";
      showAppView(target);
      if (returnContext.assistantOpen && target === "notes") {
        window.setTimeout(() => {
          setAssistantOpen(true, { persist: false });
          els.assistantQuestion?.focus();
        }, 100);
      }
    } catch {
      setState("failed", "保存失败", "测试已通过，但无法写入 Windows 凭据管理器。Key 仍保留在当前输入框。", "error");
    }
  }

  function injectAssistantCta() {
    if (assistantObserverBusy || !els.assistantConversation) return;
    assistantObserverBusy = true;
    try {
      const hasConfiguredModel = Boolean(configuredKey() || lastHealthData?.llm_model_configured);
      const latest = Array.isArray(assistantMessages) ? [...assistantMessages].reverse().find(item => item?.role === "assistant" && !item.loading) : null;
      const needsModel = !hasConfiguredModel || latest?.warning === "missing_api_key";
      if (!needsModel || els.assistantConversation.querySelector(".assistant-model-cta")) return;
      const host = els.assistantConversation.querySelector(".assistant-message.assistant:last-of-type") || els.assistantConversation.querySelector(".assistant-empty");
      if (!host) return;
      const cta = document.createElement("section");
      cta.className = "assistant-model-cta";
      cta.innerHTML = `<strong>当前使用本地证据回答</strong><small>配置模型后可以获得更完整的解释，保存后会自动回到这里。</small><button type="button" data-open-model-setup data-model-reason="assistant">一键配置模型</button>`;
      host.appendChild(cta);
    } finally {
      assistantObserverBusy = false;
    }
  }

  ui.quickChoices.addEventListener("click", event => {
    const button = event.target.closest("[data-quick-model-provider]");
    if (button) selectProvider(button.dataset.quickModelProvider);
  });
  ui.openProvider.addEventListener("click", openProviderConsole);
  ui.discover.addEventListener("click", () => runCheck("models"));
  ui.test.addEventListener("click", () => runCheck("chat"));
  ui.finish.addEventListener("click", finish);
  els.llmProvider?.addEventListener("change", () => { verifiedFingerprint = ""; window.setTimeout(syncProviderUi, 0); });
  for (const control of [els.llmModel, els.llmBaseUrl, els.llmApiKey]) {
    control?.addEventListener("input", () => { verifiedFingerprint = ""; syncProviderUi(); });
  }
  document.addEventListener("click", event => {
    const trigger = event.target.closest("[data-open-model-setup], #onboardingModelButton");
    if (!trigger) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    open({ provider: trigger.dataset.modelProvider || "", reason: trigger.dataset.modelReason || "shortcut" });
  }, true);
  const observer = new MutationObserver(() => window.queueMicrotask(injectAssistantCta));
  if (els.assistantConversation) observer.observe(els.assistantConversation, { childList: true, subtree: true });
  window.addEventListener("pywebviewready", () => window.setTimeout(syncProviderUi, 100));

  renderQuickChoices();
  injectAssistantCta();
  window.LearnNoteModelSetup = Object.freeze({ open, runCheck, providerUrls: PROVIDER_KEY_URLS });
})();
