// Unsent text stays on this device and is removed after successful delivery.
export function createDraftStore(storage, key = "learnnote.assistant.drafts") {
  let entries = {};
  const limit = 30;
  try {
    const saved = JSON.parse(storage?.getItem(key) || "{}");
    if (saved && typeof saved === "object" && !Array.isArray(saved))
      for (const [scope, value] of Object.entries(saved))
        if (validScope(scope) && typeof value?.text === "string")
          entries[scope] = {
            text: value.text.slice(0, 1000),
            updated: Number.isFinite(value.updated) ? value.updated : 0,
          };
  } catch {}
  let updated = Math.max(
    0,
    ...Object.values(entries).map((item) => item.updated),
  );
  function validScope(scope) {
    return scope === "global" || /^(task|material):[\w-]{1,160}$/.test(scope);
  }
  function persist() {
    entries = Object.fromEntries(
      Object.entries(entries)
        .filter(([, item]) => item.text.trim())
        .sort((a, b) => b[1].updated - a[1].updated)
        .slice(0, limit),
    );
    try {
      if (!storage) return false;
      if (Object.keys(entries).length)
        storage.setItem(key, JSON.stringify(entries));
      else storage.removeItem(key);
      return true;
    } catch {
      return false;
    }
  }
  return {
    get(scope) {
      return validScope(scope) ? entries[scope]?.text || "" : "";
    },
    set(scope, text) {
      if (!validScope(scope)) return;
      updated = Math.max(Date.now(), updated + 1);
      entries[scope] = { text: String(text || "").slice(0, 1000), updated };
      return persist();
    },
  };
}
