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
    ,"界面": "Interface"
    ,"默认行为": "Default behavior"
    ,"完成后打开笔记": "Open the note when complete"
    ,"任务完成时切换到笔记结果": "Open the note result when the task completes"
    ,"任务完成通知": "Task completion notification"
    ,"使用系统通知提醒": "Use a system notification"
    ,"进入笔记时收起笔记列表": "Collapse the note list when opening a note"
    ,"默认保留列表，方便在不同笔记之间切换": "Keep the list visible so you can switch between notes"
    ,"首次使用引导": "First-run guide"
    ,"重新检查本地服务、浏览器扩展和 AI 模型": "Recheck the local service, browser extension, and AI model"
    ,"AI 模型": "AI model"
    ,"用于文字整理和画面理解。": "Used for text organization and visual understanding."
    ,"Windows 凭据管理器": "Windows Credential Manager"
    ,"API Key 可加密保存到当前 Windows 用户": "The API key can be encrypted for the current Windows user"
    ,"保存当前 Key": "Save current key"
    ,"清除": "Clear"
    ,"转写": "Transcription"
    ,"优先使用字幕，没有字幕时再识别音频。": "Use subtitles first; transcribe audio only when subtitles are unavailable."
    ,"笔记细节": "Note details"
    ,"主页预设会自动选择合适组合，也可以在这里精细调整。": "Home presets choose a suitable combination; fine-tune it here when needed."
    ,"视频处理": "Video processing"
    ,"控制切片密度与笔记结构。": "Control frame density and note structure."
    ,"下载与存储": "Downloads and storage"
    ,"客户端只连接本机后端。": "The client connects only to the local backend."
    ,"后端地址": "Backend address"
    ,"修改后重新载入客户端": "Reload the client after changing this"
    ,"视频与笔记保存位置": "Video and note location"
    ,"正在读取...": "Reading..."
    ,"本地": "Local"
    ,"更改位置": "Change location"
    ,"打开文件夹": "Open folder"
    ,"资料库索引": "Library index"
    ,"只备份本地搜索索引；任务 JSON 和视频仍保留在原目录": "Back up only the local search index; task JSON and videos remain in their original folders"
    ,"检查重复": "Check duplicates"
    ,"导出索引备份": "Export index backup"
    ,"恢复索引": "Restore index"
    ,"导入学习资料": "Import study materials"
    ,"PDF、Markdown 和网页 HTML 只在本机提取文本，保留可追溯来源。": "PDF, Markdown, and web HTML are extracted locally with traceable sources preserved."
    ,"本地资料库检索": "Search local library"
    ,"回答只使用已索引的本地证据；没有证据时不会编造。": "Answers use indexed local evidence only; no evidence means no invented answer."
    ,"本地复习卡片": "Local review cards"
    ,"只读取你确认过的卡片和复习记录，不读取课程平台进度。": "Use only cards and review records you confirmed; course-platform progress is not read."
    ,"查看到期卡片": "View due cards"
    ,"导出复习记录": "Export review records"
    ,"本地学习计划": "Local study plan"
    ,"设置每天目标；暂停只影响本地提醒和复习视图，不读取课程平台进度。": "Set a daily target; pausing affects only local reminders and review views."
    ,"每日复习目标": "Daily review target"
    ,"暂停": "Pause"
    ,"保存计划": "Save plan"
    ,"新位置已经准备好": "The new location is ready"
    ,"立即重启": "Restart now"
    ,"已用空间": "Storage used"
    ,"正在统计任务和视频文件": "Counting task and video files"
    ,"链接生成前预检": "Preflight before generating links"
    ,"先确认媒体是否可访问": "Confirm that the media is reachable first"
    ,"清理旧任务": "Clean up old tasks"
    ,"保留最近 10 个任务，只清理 30 天前的已结束任务": "Keep the 10 most recent tasks; clean up finished tasks older than 30 days"
    ,"查看可清理内容": "Preview cleanup"
    ,"确认清理": "Confirm cleanup"
    ,"删除全部任务": "Delete all tasks"
    ,"删除全部已结束任务及其独占本地文件；运行中的任务不会被删除": "Delete all finished tasks and their exclusive local files; running tasks are kept"
    ,"删除全部": "Delete all"
    ,"客户端版本": "Client version"
    ,"正在检查扩展兼容性": "Checking extension compatibility"
    ,"桌面客户端": "Desktop client"
    ,"检查并安装 LearnNote 正式版本": "Check for and install the LearnNote release"
    ,"本版本更新": "Release notes"
    ,"检查更新": "Check for updates"
    ,"下载并安装": "Download and install"
    ,"GitHub 版本页": "GitHub release page"
    ,"浏览器扩展": "Browser extension"
    ,"用于把当前播放页交给客户端": "Send the current playback page to the client"
    ,"安装扩展": "Install extension"
    ,"隐私": "Privacy"
    ,"视频与任务产物默认保留在本机。": "Videos and task artifacts stay on this device by default."
    ,"不会写入任务记录或导出文件": "Not written to task records or export files"
    ,"仅本次会话": "This session only"
    ,"浏览器 Cookie": "Browser cookies"
    ,"仅在点击创建任务时读取相关域": "Read for the relevant domain only when you create a task"
    ,"按需读取": "Read on demand"
    ,"新建学习笔记": "New learning note"
    ,"选择视频来源，确认内容无误后再生成笔记。": "Choose a video source, verify its contents, then generate the note."
    ,"粘贴视频链接": "Paste a video link"
    ,"B 站、YouTube 或媒体直链": "Bilibili, YouTube, or a direct media link"
    ,"从浏览器接收当前视频": "Receive the current video from the browser"
    ,"读取扩展刚刚发送的播放内容": "Read the playback content just sent by the extension"
    ,"拖入本地视频": "Drop a local video"
    ,"MP4、MKV、WebM、MOV、M4S": "MP4, MKV, WebM, MOV, or M4S"
    ,"视频链接": "Video link"
    ,"粘贴要学习的视频": "Paste the video you want to study"
    ,"识别视频": "Inspect video"
    ,"本地视频": "Local video"
    ,"拖入文件或从电脑选择": "Drop a file or choose one from your computer"
    ,"把视频拖到这里": "Drop the video here"
    ,"选择文件后只做检查，不会立即上传": "Choosing a file only checks it; it is not uploaded immediately"
    ,"浏览器交接": "Browser handoff"
    ,"等待当前视频": "Waiting for the current video"
    ,"保持视频正在播放，在扩展里点击“发送到 LearnNote”。": "Keep the video playing and click “Send to LearnNote” in the extension."
    ,"正在连接客户端与扩展": "Connecting the client and extension"
    ,"重新检查": "Check again"
    ,"进入后会自动接收，不需要反复刷新。": "It will be received automatically; repeated refreshes are not needed."
    ,"继续上次任务": "Continue the last task"
    ,"继续": "Continue"
    ,"视频已识别": "Video identified"
    ,"确认视频内容": "Confirm video content"
    ,"开始前检查声音、字幕和画面是否完整。": "Check audio, subtitles, and visuals before starting."
    ,"时长": "Duration"
    ,"声音": "Audio"
    ,"字幕": "Subtitles"
    ,"画面": "Visuals"
    ,"预计耗时": "Estimated time"
    ,"正在估算": "Estimating"
    ,"笔记用途": "Note purpose"
    ,"这次准备怎么学？": "How will you study this?"
    ,"导入 YAML / JSON": "Import YAML / JSON"
    ,"课堂复习": "Class review"
    ,"知识点、解释、易错点、复习题": "Concepts, explanations, pitfalls, and review questions"
    ,"操作教程": "Operation tutorial"
    ,"步骤、界面变化、命令、常见错误": "Steps, UI changes, commands, and common errors"
    ,"考试整理": "Exam review"
    ,"定义、考点、记忆卡片、练习题": "Definitions, exam points, flashcards, and exercises"
    ,"快速摘要": "Quick summary"
    ,"结论和关键时间轴": "Conclusions and key timestamps"
    ,"自定义模板": "Custom template"
    ,"导入自己的结构": "Import your own structure"
    ,"开始生成笔记": "Start generating note"
    ,"正在生成": "Generating"
    ,"处理视频内容": "Processing video"
    ,"准备任务...": "Preparing task..."
    ,"预计剩余": "Estimated remaining"
    ,"查看技术日志": "View technical log"
    ,"等待任务信息...": "Waiting for task information..."
    ,"选择学习内容，生成结构清晰、可以回到原视频核对的笔记。": "Choose learning material and create notes you can verify against the original video."
    ,"当前页面": "Current page"
    ,"从扩展侧栏读取正在播放的视频": "Read the playing video from the extension side panel"
    ,"解析网页或直接媒体链接": "Parse a page or direct media link"
    ,"拖入 mp4、flv、avi、mkv、webm 等文件": "Drop mp4, flv, avi, mkv, webm, or other files"
    ,"启动就绪": "Startup ready"
    ,"正在检查本机运行环境": "Checking the local runtime"
    ,"输出预设": "Output preset"
    ,"高级设置": "Advanced settings"
    ,"智能整理": "Smart organization"
    ,"根据内容自动选择结构": "Choose a structure automatically from the content"
    ,"课堂精讲": "Deep lecture review"
    ,"概念脉络 · 例题步骤 · 易错点": "Concept map · worked steps · common pitfalls"
    ,"考前梳理": "Exam preparation"
    ,"考点总结 · 公式定理 · 自测题": "Exam points · formulas · self-tests"
    ,"最近笔记": "Recent notes"
    ,"查看全部": "View all"
    ,"处理参数": "Processing parameters"
    ,"切片、转写、图文总结模型": "Frames, transcription, and visual summary models"
    ,"切片间隔": "Frame interval"
    ,"秒/帧": "sec/frame"
    ,"视觉窗口": "Visual window"
    ,"转写引擎": "Transcription engine"
    ,"转写模型": "Transcription model"
    ,"笔记风格": "Note style"
    ,"笔记格式": "Note format"
    ,"恢复默认": "Reset defaults"
    ,"导出 Markdown": "Export Markdown"
    ,"本版本更新": "Release notes"
    ,"页面布局": "Page layout"
    ,"主导航": "Main navigation"
    ,"设置分类": "Settings categories"
    ,"外观实时预览": "Live appearance preview"
    ,"本地资料库检索结果": "Local library search results"
    ,"到期复习卡片": "Due review cards"
    ,"选择视频来源": "Choose a video source"
    ,"返回来源选择": "Back to source choices"
    ,"等待浏览器发送": "Waiting for the browser to send"
    ,"重新选择视频": "Choose another video"
    ,"选择笔记用途": "Choose a note purpose"
    ,"学习入口路线": "Learning entry route"
    ,"视频来源": "Video source"
    ,"启动就绪检查": "Startup readiness check"
    ,"链接预检报告": "Link preflight report"
    ,"当前页直取启动面板": "Current-page capture panel"
    ,"当前页交接流程": "Current-page handoff flow"
    ,"当前页直取状态": "Current-page capture status"
    ,"最近笔记": "Recent notes"
    ,"学习生产线": "Learning workflow"
    ,"笔记风格预览": "Note style preview"
    ,"处理流程": "Processing workflow"
    ,"任务状态筛选": "Task status filter"
    ,"任务结果": "Task result"
    ,"关闭引导": "Close guide"
    ,"AI 学习侧栏": "AI study sidebar"
    ,"扩宽 AI 侧栏": "Widen AI sidebar"
    ,"扩宽侧栏": "Widen sidebar"
    ,"收起 AI 侧栏": "Collapse AI sidebar"
    ,"收起侧栏": "Collapse sidebar"
    ,"发送问题": "Send question"
    ,"针对这篇笔记提问...": "Ask about this note..."
    ,"高级导出与诊断": "Advanced exports and diagnostics"
    ,"高级导出和诊断": "Advanced exports and diagnostics"
    ,"复制笔记": "Copy note"
    ,"删除全部已结束任务": "Delete all finished tasks"
    ,"任务结果": "Task result"
    ,"生成另一个版本": "Generate another version"
    ,"重新整理这篇笔记": "Rework this note"
    ,"复用已经下载的视频，不重新下载。": "Reuse the downloaded video without downloading again."
    ,"关闭更新说明": "Close release notes"
    ,"关闭": "Close"
    ,"BV 号或 https://...": "BV ID or https://..."
    ,"默认使用页面标题或文件名": "Use the page title or filename by default"
    ,"搜索术语或问题": "Search terms or questions"
    ,"搜索标题、来源或错误": "Search titles, sources, or errors"
    ,"留空则使用后端环境变量或本地降级": "Leave blank to use the backend environment or local fallback"
    ,"获取视频": "Get video"
    ,"检查内容": "Check content"
    ,"生成字幕": "Generate transcript"
    ,"理解画面": "Understand visuals"
    ,"整理笔记": "Organize notes"
    ,"课堂复习": "Class review"
    ,"按知识点组织解释，保留易错点并在末尾生成复习题。": "Organize explanations by concept, keep pitfalls, and add review questions."
    ,"课程主题": "Course topic"
    ,"核心知识点": "Core concepts"
    ,"概念解释": "Concept explanations"
    ,"易错点": "Common pitfalls"
    ,"复习题": "Review questions"
    ,"跟随演示顺序记录界面变化、命令、操作步骤和排错方法。": "Follow the demonstration order for UI changes, commands, steps, and troubleshooting."
    ,"完成目标": "Goal"
    ,"准备工作": "Preparation"
    ,"操作步骤": "Steps"
    ,"命令与参数": "Commands and parameters"
    ,"常见错误": "Common errors"
    ,"把定义和考点整理成便于记忆、自测和回顾的复习材料。": "Turn definitions and exam points into material for memory, self-tests, and review."
    ,"考试范围": "Exam scope"
    ,"核心定义": "Core definitions"
    ,"高频考点": "Frequent exam points"
    ,"记忆卡片": "Flashcards"
    ,"练习题": "Exercises"
    ,"只保留结论、关键依据和可以回到原视频核对的时间点。": "Keep conclusions, key evidence, and timestamps you can verify in the original video."
    ,"一句话结论": "One-line conclusion"
    ,"关键要点": "Key points"
    ,"重要时间轴": "Important timeline"
    ,"浏览器当前页": "Current browser page"
    ,"视频已识别": "Video identified"
    ,"暂未获取": "Not available yet"
    ,"已发现": "Found"
    ,"缺少声音": "Audio missing"
    ,"未发现": "Not found"
    ,"可在转写后生成": "Can be generated during transcription"
    ,"缺少画面": "Visuals missing"
    ,"这个文件没有声音轨，补充音频或重新获取完整视频后才能生成可靠笔记。": "This file has no audio track. Add audio or obtain a complete video for reliable notes."
    ,"没有检测到视频画面，请重新选择媒体。": "No video track was detected. Choose another media file."
    ,"先导入自定义模板": "Import a custom template first"
    ,"支持 YAML 或 JSON，需包含 name、prompt 和 sections。": "YAML or JSON is supported and must include name, prompt, and sections."
    ,"按自定义结构整理": "Organize with the custom structure"
    ,"模板文件不能超过 64 KB": "Template files must be 64 KB or smaller"
    ,"模板需要 name、prompt 和至少一个 sections 条目": "The template needs name, prompt, and at least one sections entry"
    ,"模板导入失败：文件格式不正确": "Template import failed: invalid file format"
    ,"正在检查视频轨道和时长...": "Checking video tracks and duration..."
    ,"已使用本机视频信息完成检查；上传将在确认后开始。": "Local video checks are complete; upload starts after confirmation."
    ,"正在识别视频信息...": "Inspecting video information..."
    ,"链接识别失败": "Link inspection failed"
    ,"没有识别到可用视频，请检查链接或登录状态。": "No usable video was found. Check the link or sign-in state."
    ,"扩展尚未连接": "Extension not connected"
    ,"正在读取扩展交接状态...": "Reading extension handoff status..."
    ,"正在等待扩展发送当前视频...": "Waiting for the extension to send the current video..."
    ,"正在创建任务...": "Creating task..."
    ,"本地视频上传失败。": "Local video upload failed."
    ,"任务没有返回有效编号": "The task did not return a valid ID"
    ,"任务创建失败，请重试。": "Task creation failed. Try again."
    ,"笔记已经整理完成": "The note is ready"
    ,"没有找到可下载的视频资源": "No downloadable video resource was found"
    ,"登录状态已失效，请重新打开视频页": "Your sign-in state expired. Reopen the video page."
    ,"该视频不能通过当前页面直接获取": "This video cannot be acquired directly from the current page"
    ,"视频服务器拒绝了下载请求": "The video server rejected the download request"
    ,"暂时无法合并这个视频流": "This video stream cannot be combined yet"
    ,"字幕或画面依据不足，已停止生成": "Subtitle or visual evidence is insufficient; generation stopped"
    ,"客户端上次处理中断，可以重新尝试": "The previous task was interrupted; you can retry"
    ,"视频交接已失效，请回到原视频页重新发送": "The video handoff expired; return to the video page and send it again"
    ,"处理未完成，请按下方建议继续": "Processing did not finish; follow the recovery steps below"
    ,"正在获取视频文件": "Getting the video file"
    ,"正在核对声音、字幕和画面": "Checking audio, subtitles, and visuals"
    ,"正在生成可核对的字幕": "Generating verifiable subtitles"
    ,"正在提取关键画面": "Extracting key visuals"
    ,"正在整理笔记结构": "Organizing the note structure"
    ,"正在准备任务": "Preparing task"
    ,"浏览器已发送": "Sent by browser"
    ,"任务仍在处理": "Task in progress"
    ,"最近完成": "Recently completed"
    ,"确认声音、字幕和画面后再开始": "Confirm audio, subtitles, and visuals before starting"
    ,"查看进度": "View progress"
    ,"笔记、字幕和画面索引已准备好": "The note, transcript, and visual index are ready"
    ,"确认视频": "Confirm video"
    ,"打开笔记": "Open note"
    ,"本次处理未完成。": "This task did not finish."
  });

  let activeLocale = "zh-CN";
  let observerInstalled = false;
  let observerScheduled = false;

  function applyStaticAttributes(roots, locale) {
    const attributes = ["aria-label", "title", "placeholder"];
    roots.forEach(root => {
      const elements = [root, ...(root.querySelectorAll?.("*") || [])];
      elements.forEach(element => {
        if (!element?.getAttribute || element.closest?.(".markdown-note, [data-user-content]")) return;
        attributes.forEach(attribute => {
          const current = element.getAttribute(attribute);
          element.__learnnoteDefaultAttributes ||= {};
          const original = element.__learnnoteDefaultAttributes[attribute] || current;
          if (!original || !staticText[original]) return;
          element.__learnnoteDefaultAttributes[attribute] ||= original;
          element.setAttribute(attribute, locale === "en-US" ? staticText[original] : original);
        });
      });
    });
  }

  function scheduleDynamicApply(document) {
    if (activeLocale !== "en-US" || observerScheduled) return;
    observerScheduled = true;
    const schedule = global.queueMicrotask || (callback => global.setTimeout(callback, 0));
    schedule(() => {
      observerScheduled = false;
      applyStatic(document, activeLocale);
    });
  }

  function installObserver(document) {
    if (observerInstalled || !global.MutationObserver || !document?.body) return;
    const observer = new global.MutationObserver(() => scheduleDynamicApply(document));
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    observerInstalled = true;
  }

  function applyStatic(document, locale) {
    if (!document?.createTreeWalker) return;
    activeLocale = locale === "en-US" ? "en-US" : "zh-CN";
    installObserver(document);
    const roots = document.querySelectorAll(".topbar, #mainNavigation, #settingsView, #workspace, #onboardingOverlay, #aiAssistantDrawer, #noteVersionOverlay, #releaseNotesOverlay");
    const walker = document.createTreeWalker(document.body, 4);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!parent || ![...roots].some(root => root.contains(parent))) continue;
      if (parent.closest("[data-i18n], input, textarea, script, style, .markdown-note, [data-user-content]")) continue;
      const current = node.nodeValue ?? "";
      const previousTranslation = node.__learnnoteLastTranslatedText;
      let original = node.__learnnoteDefaultText;
      if (original === undefined || (previousTranslation && current !== previousTranslation)) {
        const candidate = current;
        const candidateText = candidate.trim();
        if (staticText[candidateText]) {
          original = candidate;
          node.__learnnoteDefaultText = original;
        }
      }
      if (locale !== "en-US") {
        if (original !== undefined) node.nodeValue = original;
        node.__learnnoteLastTranslatedText = node.nodeValue ?? "";
        continue;
      }
      if (original === undefined) continue;
      const trimmed = original.trim();
      if (!trimmed || !staticText[trimmed]) continue;
      const leading = original.slice(0, original.indexOf(trimmed));
      const trailing = original.slice(original.indexOf(trimmed) + trimmed.length);
      const translated = `${leading}${staticText[trimmed]}${trailing}`;
      if (node.nodeValue !== translated) node.nodeValue = translated;
      node.__learnnoteLastTranslatedText = translated;
    }
    applyStaticAttributes(roots, locale);
  }

  global.LearnNoteI18n = Object.freeze({ copy, applyStatic });
})(typeof globalThis !== "undefined" ? globalThis : window);
