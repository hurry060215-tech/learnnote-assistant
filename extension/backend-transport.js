// Local backend transport adapter; all storage, network, clock and timer effects are supplied explicitly.
(function (root) {
function createBackendTransport({ getStorage, fetch, hasFetch, getExtensionVersion, now, setTimeout, clearTimeout, createAbortController, defaultBackendUrl: DEFAULT_BACKEND_URL, protocolVersion: EXTENSION_PROTOCOL_VERSION }) {
  async function storedBackendUrl() {
    if (!getStorage()?.local?.get) return DEFAULT_BACKEND_URL;
    try {
      const stored = await getStorage().local.get(["backendUrl"]);
      const value = String(stored?.backendUrl || "").trim();
      if (/^http:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?$/i.test(value)) return value;
    } catch {
      // Use the stable desktop default when extension storage is unavailable.
    }
    return DEFAULT_BACKEND_URL;
  }

  async function pairingHeaders(backendUrl, headers = {}) {
    const normalized = String(backendUrl || DEFAULT_BACKEND_URL).replace(/\/$/, "");
    try {
      const stored = await getStorage().local.get({ pairingTokens: {} });
      const cached = stored?.pairingTokens?.[normalized];
      if (!cached || Number(cached.expiresAt || 0) <= now() + 15000) {
        const response = await fetch(`${normalized}/api/pairing/issue`);
        const payload = await response.json().catch(() => ({}));
        if (response.ok && payload?.token) {
          const pairingTokens = { ...(stored?.pairingTokens || {}), [normalized]: {
            token: String(payload.token),
            expiresAt: Number(payload.expires_at || 0) * 1000
          }};
          await getStorage().local.set({ pairingTokens });
          return { ...headers, "X-LearnNote-Pairing": String(payload.token) };
        }
      } else {
        return { ...headers, "X-LearnNote-Pairing": String(cached.token) };
      }
    } catch {
      // The backend will return a clear 401 if pairing is unavailable.
    }
    return { ...headers };
  }

  async function sendBackendHeartbeat(backendUrl) {
    if (!hasFetch()) return false;
    const extensionVersion = String(getExtensionVersion() || "");
    const controller = createAbortController();
    const timer = controller ? setTimeout(() => controller.abort(), 3000) : 0;
    try {
      const response = await fetch(`${backendUrl}/api/extension/heartbeat`, {
        method: "POST",
        ...(controller ? { signal: controller.signal } : {}),
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          extension_version: extensionVersion,
          protocol_version: EXTENSION_PROTOCOL_VERSION,
          source: "background"
        })
      });
      if (!response?.ok) return false;
      const payload = await response.json();
      return payload?.ok === true && payload.extension_connected === true && payload.protocol_version === EXTENSION_PROTOCOL_VERSION;
    } catch {
      return false;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  function backendErrorMessage(payload, fallback) {
    const detail = payload?.detail;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (detail?.message) return String(detail.message);
    if (payload?.message) return String(payload.message);
    if (payload?.error) return String(payload.error);
    return fallback;
  }

  async function backendJsonResponse(res, fallback) {
    const payload = await res.json().catch(() => ({}));
    if (res.ok === false) {
      return {
        ...payload,
        ok: false,
        error: backendErrorMessage(payload, fallback || `HTTP ${res.status}`),
        status: res.status
      };
    }
    return payload;
  }

  async function postJsonWithRetry(url, body, fallback, attempts = 2, beforeSend = null) {
    let lastError = null;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        const headers = await pairingHeaders(new URL(url).origin, { "Content-Type": "application/json" });
        const blocked = beforeSend ? await beforeSend() : null;
        if (blocked) return blocked;
        const response = await fetch(url, {
          method: "POST",
          headers,
          body: JSON.stringify(body)
        });
        if (response.ok !== false || response.status < 500 || attempt === attempts - 1) {
          return await backendJsonResponse(response, fallback);
        }
      } catch (error) {
        lastError = error;
        if (attempt === attempts - 1) break;
      }
      await new Promise(resolve => setTimeout(resolve, 250 * (attempt + 1)));
    }
    return { ok: false, error: lastError?.message || fallback };
  }

  return Object.freeze({ storedBackendUrl, pairingHeaders, sendBackendHeartbeat, backendErrorMessage, backendJsonResponse, postJsonWithRetry });
}

root.LearnNoteBackendTransport = Object.freeze({
  createBackendTransport,
});
})(globalThis);
