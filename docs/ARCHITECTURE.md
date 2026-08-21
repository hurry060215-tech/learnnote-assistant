# LearnNote 架构边界

LearnNote 当前采用“行为不变、逐步拆分”的策略。任务目录中的 JSON 仍是事实源，SQLite/事件日志/前端状态均为可重建投影。

## 后端依赖方向

```text
API routers (routers/*.py)
  -> application flows (processor.py)
      -> domain models (models.py)
      -> adapters/downloader/media
      -> storage/library/knowledge/study/observability
```

- `models.py` 只定义版本化输入/输出 schema，不读取文件、不发网络请求。
- `storage.py` 负责任务 JSON、迁移和生命周期；不决定媒体来源策略。
- `library.py`、`knowledge.py`、`study.py` 和 `observability.py` 都是本地可重建投影，不能成为任务事实源。
- `adapters.py` 是来源契约；站点特例不能反向污染 API 或任务模型。
- `downloader.py` 只负责候选排序、预检和下载策略；不生成学习笔记。
- `media_kinds.py` 只负责无网络的媒体类型识别和有效类型归一化；`downloader.py` 保留兼容导出，避免旧调用方迁移时改变行为。
- `media_candidate_ranking.py` 只负责候选评分、播放匹配、伴随音频配对和去重；页面扫描/Manifest 推断仍由 downloader 编排后交给该纯决策模块。
- `media_transport.py` 负责 SSRF 防护、DNS 结果固定、TLS/HTTP 连接、重定向和响应包装；它不决定候选来源或笔记内容。
- `asr_pipeline.py` 负责本地/远程 ASR 选择、转写进度心跳和 ASR 失败分类；它通过 processor_state 检查取消，不直接编排视频阶段。
- `local_video_task.py` 负责本地视频入口的资源监控、取消和统一错误收口；实际视频阶段通过注入的处理函数执行，避免入口逻辑复制。
- `visual_pipeline.py` 负责抽帧、画面网格、重要帧标记和视觉索引写入；`processor.py` 只编排字幕、视觉窗口、证据门禁和总结阶段。
- `page_text_pipeline.py` 负责页面文本/浏览器字幕兜底产物和脱敏总结诊断写入；processor 只注入现有字幕、总结和诊断回调，保持兼容 patch 点。
- `transcript_pipeline.py` 负责字幕选择、浏览器字幕回退、内嵌字幕解析、ASR 产物和证据覆盖收口；processor 只编排视觉与总结阶段。
- `note_pipeline.py` 负责证据覆盖门禁、总结调用、诊断和最终 note 状态写回；processor 只串联媒体、转写、视觉和 note 阶段。
- `downloader_policy.py` 只保存下载错误分类、重试优先级和 yt-dlp 进程策略；它不发起网络请求，便于独立测试和复用。
- `processor_state.py` 只负责取消、失败收口、checkpoint、证据门禁和资源报告；`processor.py` 负责阶段编排，不把状态持久化细节重新复制回流水线。
- `summary_diagnostics.py` 只负责总结/视觉调用的脱敏诊断计划和失败分类；`processor.py` 只负责把诊断结果接回任务阶段，不直接维护诊断规则。
- `routers/knowledge_study.py` owns knowledge and study routes; `routers/library.py`
  owns index/search/backup/restore routes; `routers/system.py` owns integration,
  desktop-focus, and preference routes. They import domain services directly and
  never import `main.py`, preventing route registration from becoming a second
  application-service boundary.

## 前端边界

- `web/app.js` 只负责 UI 编排和 API 调用；资料库导入、检索、复习动作使用独立函数，不能把 Cookie 或模型 Key 写入 localStorage。
- `web/i18n.js` 只提供版本化的界面文案资源；应用脚本通过 `LearnNoteI18n` 读取文案，缺失资源时回退到 HTML 默认中文，不阻断任务流程。
- `web/markdown.js` 负责 Markdown 渲染、笔记目录和浏览器页上下文清理；`app.js` 通过兼容调用使用它，不让渲染规则继续扩散到任务编排代码。
- `web/task-links.js` 负责任务导出、恢复、重跑和 QA URL 构造；任务链接必须统一编码任务 ID 和窗口 ID。
- `extension/` 只负责用户触发的当前页采集和本地交接；不执行转写、总结或后台录屏。
- `integrations/` 只能通过版本化 manifest 和导出端点读取任务；不得读取 LearnNote 内部路径。

## 拆分验收

新模块必须拥有：公开输入/输出 schema、至少一个离线测试、失败恢复动作、隐私说明和迁移/重建路径。大型单体的进一步拆分应保持旧 API、任务文件和导出路径兼容。CI 现在同时检查依赖方向和 `main.py`、`downloader.py`、`processor.py`、`web/app.js`、`web/styles.css` 的行数上限，防止重构后继续膨胀。当前已完成知识/学习与系统路由的第一阶段拆分；下载器、处理器和前端仍按同一策略继续拆分。
