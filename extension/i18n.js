(function () {
  const fallback = {
    extensionName: "LearnNote 当前视频助手",
    extensionDescription: "识别当前正在播放的视频，并安全交接到本机 LearnNote 客户端。",
    actionTitle: "打开 LearnNote 当前视频助手",
  };
  function message(key, defaultValue = fallback[key] || key) {
    try {
      const value = globalThis.chrome?.i18n?.getMessage?.(key);
      return value || defaultValue;
    } catch {
      return defaultValue;
    }
  }
  function apply(root = document) {
    root.querySelectorAll?.("[data-i18n]").forEach((node) => {
      node.textContent = message(node.dataset.i18n, node.textContent);
    });
    root.querySelectorAll?.("[data-i18n-aria]").forEach((node) => {
      node.setAttribute("aria-label", message(node.dataset.i18nAria, node.getAttribute("aria-label") || ""));
    });
    root.querySelectorAll?.("[data-i18n-title]").forEach((node) => {
      node.title = message(node.dataset.i18nTitle, node.title);
    });
    root.documentElement?.setAttribute("lang", globalThis.chrome?.i18n?.getUILanguage?.()?.startsWith("en") ? "en" : "zh-CN");
  }
  globalThis.LearnNoteI18n = { message, apply };
})();
