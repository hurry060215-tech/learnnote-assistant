import { api } from "/web/desk-api.js";

// Only connection metadata crosses back into a page. Keys stay in the local
// service/OS credential store, so changing browser or port does not lose them.
export async function loadModelConnection(state) {
  const epoch = state.modelSaveEpoch || 0;
  const result = await api("/api/model/connection");
  if (
    epoch !== (state.modelSaveEpoch || 0) ||
    document.getElementById("settingsDialog")?.dataset.unsaved
  )
    return result;
  if (result.model) {
    state.model = result.model;
    state.key = "";
    localStorage.setItem("learnnote.desk.model", JSON.stringify(state.model));
  } else if (state.model.use_saved_connection) {
    // The shared connection may have been cleared in another window. Do not
    // silently resurrect that endpoint from this page's localStorage.
    state.model = {};
    state.key = "";
    localStorage.removeItem?.("learnnote.desk.model");
  }
  state.modelConnectionReady = Boolean(result.model && result.configured);
  state.modelConnectionMessage = result.message;
  state.modelConnectionStorage = result.storage;
  window.dispatchEvent(new CustomEvent("learnnote:settings"));
  return result;
}

export function installConnections({ state, notice }) {
  const $ = (id) => document.getElementById(id);
  const pane = document.querySelector('[data-settings-page="model"]');
  if (!pane) return;
  const box = document.createElement("section");
  box.className = "settings-connection";
  box.innerHTML = `<h4>账号连接</h4><p class="muted">OpenRouter 支持浏览器授权。MiMo 等服务使用 API Key；LearnNote 本身无需登录。</p><p id="providerConnectionStatus" role="status">正在检查连接…</p><div class="settings-inline-actions"><button type="button" id="connectOpenRouter">登录 OpenRouter</button><button type="button" id="useOpenRouter" hidden>使用已连接账号</button><button type="button" id="disconnectOpenRouter" hidden>断开连接</button></div>`;
  pane.append(box);
  async function refreshConnection() {
    try {
      const result = await api("/api/connections");
      const connected = result.openrouter.connected;
      window.dispatchEvent(new CustomEvent("learnnote:settings"));
      $("providerConnectionStatus").textContent = connected
        ? `OpenRouter 已连接 · ${result.openrouter.storage === "system" ? "凭据保存在系统凭据库" : "连接保留到本机服务关闭"}`
        : "尚未连接 OpenRouter，可以继续使用上方的 API Key 设置。";
      $("useOpenRouter").hidden = $("disconnectOpenRouter").hidden = !connected;
      $("connectOpenRouter").textContent = connected
        ? "重新授权"
        : "登录 OpenRouter";
    } catch {
      window.dispatchEvent(new CustomEvent("learnnote:settings"));
      $("providerConnectionStatus").textContent =
        "账号连接当前不可用；可以使用 API Key 或本机模型。";
    }
  }
  $("connectOpenRouter").onclick = async () => {
    // Create the tab during the user's click to avoid popup blocking after fetch.
    const popup = window.open(
      "about:blank",
      "learnnote-provider-authorization",
    );
    try {
      const result = await api("/api/connections/openrouter/start", {
        method: "POST",
      });
      const target = new URL(result.authorization_url);
      if (target.origin !== "https://openrouter.ai")
        throw new Error("授权地址无效。");
      if (popup) {
        popup.opener = null;
        popup.location.href = target.href;
      } else {
        $("providerConnectionStatus").textContent =
          "浏览器阻止了新窗口，请允许弹出窗口后重试。";
        return;
      }
      $("providerConnectionStatus").textContent =
        "请在新窗口完成授权。返回后可以选择“使用已连接账号”。";
    } catch (error) {
      popup?.close();
      notice(error.message);
    }
  };
  $("useOpenRouter").onclick = async () => {
    const current =
      $("provider").value === "openrouter" ? $("model").value.trim() : "";
    const selection = {
      provider: "openrouter",
      base_url: "https://openrouter.ai/api/v1",
      model: current || "openrouter/auto",
      use_saved_connection: true,
    };
    try {
      const result = await api("/api/model/connection", {
        method: "PUT",
        body: JSON.stringify(selection),
      });
      state.model = result.model;
    } catch (error) {
      notice(error.message);
      return;
    }
    state.key = "";
    state.modelConnectionReady = true;
    localStorage.setItem("learnnote.desk.model", JSON.stringify(state.model));
    if (![...$("provider").options].some((item) => item.value === "openrouter"))
      $("provider").add(new Option("OpenRouter", "openrouter"));
    $("provider").value = "openrouter";
    $("baseUrl").value = state.model.base_url;
    $("model").value = state.model.model;
    $("apiKey").value = "";
    window.LearnNoteSettings?.modelSaved();
    window.dispatchEvent(new CustomEvent("learnnote:settings"));
    notice("已选择 OpenRouter 连接，可继续选择模型或开始整理。");
  };
  $("disconnectOpenRouter").onclick = async () => {
    try {
      await api("/api/connections/openrouter", { method: "DELETE" });
      await loadModelConnection(state);
      await refreshConnection();
    } catch (error) {
      notice(error.message);
    }
  };
  window.addEventListener("storage", (event) => {
    if (event.key !== "learnnote.desk.model") return;
    if ($("settingsDialog").dataset.unsaved) {
      notice(
        "另一窗口已更新模型连接；先保存或放弃当前设置，避免覆盖正在编辑的内容。",
      );
      return;
    }
    loadModelConnection(state)
      .then(refreshConnection)
      .catch(() => {});
  });
  window.addEventListener("focus", () => {
    loadModelConnection(state)
      .then(refreshConnection)
      .catch(() => {});
  });
  if (location.hash.includes("connection=failed"))
    notice("授权未完成或已过期，可以重新连接。");
  refreshConnection();
}
