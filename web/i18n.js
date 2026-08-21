(function installLearnNoteI18n(global) {
  "use strict";

  const copy = Object.freeze({
    "en-US": {
      settingsClose: "Back to workspace",
      advancedSettings: "Show advanced settings",
      saveSettings: "Save settings",
      resetSettings: "Reset defaults",
      settingsNav: "Settings",
      workspaceNav: "Workspace",
      notesNav: "Notes",
      historyNav: "Tasks",
      navigation: "Navigation",
      createArea: "Create",
      listArea: "List",
      focusMode: "Focus",
      assistant: "AI tutor",
      collapseNavigation: "Collapse navigation",
      collapseWorkspace: "Collapse create area",
      collapseHistory: "Collapse note list",
      readingMode: "Enter focus reading",
      settingsTitle: "Settings",
      settingsSubtitle: "Adjust the interface and video processing",
      settingsGeneral: "General",
      settingsModel: "AI model",
      settingsTranscriber: "Transcription",
      settingsNotes: "Notes",
      settingsProcessing: "Video processing",
      settingsConnection: "Downloads and storage",
      settingsPrivacy: "Privacy",
      appearanceHeading: "Interface",
      appearanceDescription: "Make common actions clearer and easier to read.",
      interfaceScale: "Interface scale",
      interfaceScaleHint: "Adjust spacing and readable text size",
      textSize: "Text size",
      textSizeHint: "Does not change the window layout",
      theme: "Theme",
      themeHint: "Follow the system or choose an appearance",
      colorTheme: "Color theme",
      colorThemeHint: "Accent color is used for actions and selection",
      localeLabel: "Interface language",
      localeHint: "Switch common navigation, settings, and action labels",
      preview: "Live preview",
      previewTitle: "Clear, restrained, easy to scan",
      previewHint: "Changes apply immediately; save at the bottom to keep them.",
      defaultBehavior: "Default behavior",
      defaultSource: "Default input",
      defaultSourceHint: "Show this source first when the client opens",
      sourceBrowser: "Current page",
      sourceLocal: "Local video",
      sourceUrl: "Video link",
      reopenOnboarding: "Open again",
      settingsAdvancedLabel: "Show advanced settings",
      settingsAdvancedHint: "Reveal model, transcription, note, and video details"
    }
  });

  const staticText = Object.freeze({
    "学习视频笔记工作台": "Video Learning Workspace",
    "检查中": "Checking",
    "导航": "Navigation",
    "创建区": "Create",
    "列表": "List",
    "专注": "Focus",
    "AI 助教": "AI tutor",
    "刷新任务": "Refresh tasks",
    "新建笔记": "New note",
    "笔记库": "Notes",
    "任务": "Tasks",
    "设置": "Settings",
    "返回工作台": "Back to workspace",
    "通用": "General",
    "AI 模型": "AI model",
    "转写": "Transcription",
    "笔记": "Notes",
    "视频处理": "Video processing",
    "下载与存储": "Downloads and storage",
    "隐私": "Privacy",
    "新建学习笔记": "New learning note",
    "从一段视频开始": "Start with a video",
    "打开笔记库": "Open notes",
    "视频链接": "Video link",
    "本地视频": "Local video",
    "浏览器交接": "Browser handoff",
    "选择文件": "Choose file",
    "生成笔记": "Generate note",
    "开始使用": "Start using",
    "稍后设置": "Set up later",
    "正在检查": "Checking",
    "稍后配置": "Configure later",
    "保存设置": "Save settings",
    "恢复默认": "Reset defaults",
    "查看诊断": "View diagnostics",
    "导出诊断": "Export diagnostics",
    "资源报告": "Resource report",
    "候选证据": "Candidate evidence",
    "预检报告": "Preflight report",
    "学习笔记": "Learning note",
    "画面与时间轴": "Visuals & timeline",
    "完整字幕": "Full transcript",
    "原始画面": "Raw frames",
    "处理检查": "Processing checks",
    "阅读笔记": "Read note",
    "看切片": "View slices",
    "核对字幕": "Check transcript",
    "知道了": "Got it",
    "版本更新": "Release notes",
    "修复与改进": "Fixes and improvements"
  });

  function applyStatic(document, locale) {
    if (!document?.createTreeWalker) return;
    const roots = document.querySelectorAll(".topbar, #mainNavigation, #settingsView, #workspace, #onboardingOverlay, #aiAssistantDrawer, #noteVersionOverlay, #releaseNotesOverlay");
    const walker = document.createTreeWalker(document.body, 4);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!parent || ![...roots].some(root => root.contains(parent))) continue;
      if (parent.closest("[data-i18n], input, textarea, select, option, script, style, .markdown-note, [data-user-content]")) continue;
      const original = node.__learnnoteDefaultText ?? node.nodeValue ?? "";
      node.__learnnoteDefaultText = original;
      if (locale !== "en-US") {
        node.nodeValue = original;
        continue;
      }
      const trimmed = original.trim();
      if (!trimmed || !staticText[trimmed]) continue;
      const leading = original.slice(0, original.indexOf(trimmed));
      const trailing = original.slice(original.indexOf(trimmed) + trimmed.length);
      node.nodeValue = `${leading}${staticText[trimmed]}${trailing}`;
    }
  }

  global.LearnNoteI18n = Object.freeze({ copy, applyStatic });
})(typeof globalThis !== "undefined" ? globalThis : window);
