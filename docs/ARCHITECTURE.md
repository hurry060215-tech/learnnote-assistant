# LearnNote 架构边界

LearnNote 当前采用“行为不变、逐步拆分”的策略。任务目录中的 JSON 是任务事实源，个人批注另存为版本化 JSON。资料原文件也属于需要保留的事实；索引是可重建投影。`task-queue.sqlite3` 是有界的执行意图日志，不保存 Cookie、API Key 或完整浏览器请求。

## 执行与恢复

- `task_queue.py` 统一接收处理请求，每个数据目录最多一个重型处理任务，最多 24 个排队/执行意图；重复排队同一 task ID 复用原 Future。
- `worker_lease.py` 使用 Windows 命名互斥量或 POSIX 文件锁，避免不同本地进程同时执行重型任务。
- 关闭后未完成的无凭据本地任务可从同一 task ID 和已保存媒体恢复；需要 Cookie、临时媒体请求或任务级 Key 的意图会转为可见的待恢复错误，要求用户重新交接。不能用错误身份或悄悄切换模型补跑。
- `upload_limits.py` 在 multipart 解析前和最终写入时检查累计大小与磁盘余量。视频上限 4 GB、保留 512 MB；预检同时考虑上传暂存与最终文件两份空间。
- 恢复资料库索引只事务性替换任务索引表，不替换包含文档和证据的整个数据库；恢复前快照继续保留。

## 正文与个人内容

- `courses.py` 保存版本化手工课程，写入时检查 revision，避免并发编辑覆盖；课程比较只返回真实引文与关键词共现，不推断同义或因果关系。播放列表只预览受限 HTTPS 平台的前 24 项，用户确认后才提交任务。
- `range_learning.py` 在队列内生成独立片段，保存来源区间；字幕边界被切断时不猜测词语归属，而是对片段转写。精确切片使用受限线程转码，原媒体保持不变。
- `local_ocr.py` 是可选 CPU 文字通道，最多识别 24 个候选帧，任务内缓存随任务生命周期清理。OCR结果包含 bbox/置信度但始终未核验；OCR-only 模式不会把图像传入视觉模型总结。
- FSRS 在 Python 边界使用 `None` 表示 Review 状态无 step，数据库继续用兼容的整数占位；新卡不使用旧的默认稳定度当作既有记忆。显式重建调度会先备份参数，评分历史不完整时保持原状态。

- `markdown_structure.py` 将代码围栏与正文区分；`note_document.py` 的 `located` 表示只有时间定位，`linked` 表示关联了原文，二者都不表示事实已核验。
- 知识证据保留原始换行与缩进；资料阅读优先读取所保存的原文件，长文分批展示并提供明确的继续阅读入口。
- `personal_notes.py` 以任务版本族或原文件 SHA-256 关联用户批注，正文重生成不会覆盖个人内容。分享导出默认不包含批注，用户可另选含批注的导出。
- `web/learning.js` 管理资料阅读、复习会话和出处弹窗；`web/personal-notes.js` 管理个人批注。Markdown 解析集中在 `web/markdown.js`；解析模块不可用时退回转义后的纯文本。
- 外部图片不会在打开本地笔记时自动加载，仍可由用户主动打开相应链接。

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
- `media_candidate_ranking.py` 只负责候选评分、播放匹配、伴随音频配对和去重；`media_source_context.py` 将现有 Manifest 推断和页面候选可信度判断接入该纯决策模块。
- `media_source_context.py` 只解释显式传入的候选、页面 URL 和请求头：保留来源身份、页面回退顺序、请求头白名单及分片推断策略，不发网络请求、不读取 Cookie、不保存任务。`downloader.py` 保留旧函数与常量导出，行数上限收紧到 2520；新模块上限 300，计入既有 9250 行合计预算。详见 [2026-10-09 来源边界记录](ISSUE_ARCHITECTURE_SOURCE_CONTEXT_20261009.md)。
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
- `web/task-list.js` 只负责任务列表的标题/媒体投影、初始选择、稳定排序、筛选、变更指纹和笔记版本族。它依赖 `task-format.js` / `task-display.js`；当前任务、筛选、任务历史和时钟由 `app.js` 在每次调用时显式传入，不读取 DOM、存储或网络。迁移图、公开契约、原实现快照和合计预算见 [2026-10-09 任务列表拆分记录](ISSUE_ARCHITECTURE_TASK_LIST_20261009.md)。
- `extension/` 只负责用户触发的当前页采集和本地交接；不执行转写、总结或后台录屏。
- `integrations/` 只能通过版本化 manifest 和导出端点读取任务；不得读取 LearnNote 内部路径。

## 拆分验收

新模块必须拥有：公开输入/输出 schema、至少一个离线测试、失败恢复动作、隐私说明和迁移/重建路径。大型单体的进一步拆分应保持旧 API、任务文件和导出路径兼容。CI 现在同时检查依赖方向和 `main.py`、`downloader.py`、`processor.py`、`web/app.js`、`web/styles.css` 的行数上限，防止重构后继续膨胀。当前已完成知识/学习与系统路由的第一阶段拆分；下载器、处理器和前端仍按同一策略继续拆分。

## 第二阶段：媒体发现与问答边界（2026-10-08，#143）

本阶段保留调用者可见的 `main.py` / `downloader.py` 函数入口，不更改 API、
`ResourceCandidate`、任务 JSON、问答历史版本 1 或导出路径。

```text
downloader (network / preflight / download orchestration)
  -> media_discovery (HTML, text, page-frame candidates)
       -> media_json_discovery (JSON, embedded fields, encoded URLs)
            -> media_url_parsing (decoding, lexical hints, normalization)
       -> media_candidate_ranking / media_kinds / models
  -> media_manifests (HLS/DASH recognition, DRM flags, relative URI rewrite)

main (routes, model access, storage adapters, existing patch points)
  -> qa_evidence (citation selection, transcript windows, prompt text)
  -> qa_history (v1 history serialization / Markdown rendering)
       -> qa_evidence
```

- 媒体发现模块只接收字符串、基础 URL 和来源标签，返回既有候选 schema；不做 DNS、
  HTTP、磁盘写入或凭据收集。找到 URL 不代表允许获取，SSRF/DRM/请求策略仍在原边界。
- `qa_evidence` 的输入/输出为现有 citation 字典及字符串；可信度、时间格式等策略由调用者
  显式传入。`qa_history` 显式接收读写、时钟、ID 回调，不选择数据路径。
- `main` 继续在调用时解析 `read_json`、`write_json`、`read_task_qa_history` 和字幕可信度
  回调，保留已有测试的替换点；下载/网络适配器继续由 `downloader` 编排。
- 失败行为不变：解析失败保留空候选/原有回退，清理后的空证据不能变成可信事实；不会新增
  持久化、遥测、权限或自动网络访问。本次无需数据迁移/重建，回滚代码即可读取旧产物。

`check-architecture.py` 现在解析所有 Python 相对/绝对/别名导入，包括函数内延迟导入，
并检测强连通分量及纯模块依赖方向。仅保留三条明确的既有延迟生命周期接线：
`library -> study`（删除来源时清理卡片）、`storage -> task_queue`（删除任务时取消队列）、
`task_queue -> range_learning`（恢复片段任务）。这些不是整模块/循环豁免；改成顶层导入或
新增循环依赖仍失败。彻底消除这三处反向接线仍是后续工作。

行数预算收紧到 `main <= 4800`、`downloader <= 2800`、`processor <= 1450`；
新模块各自有 130–440 行上限，已迁移的后端模块组另有 9250 行总预算。扩展三大脚本新增
逐文件上限及 335000 字节合计预算；历史 `app.js` / `styles.css` 上限也收紧，但本阶段
没有声称完成它们的实质拆分。现有 CI 的架构检查无需新 workflow 即可执行这些规则。

离线行为快照位于 `backend/tests/fixtures/architecture_extraction_v1.json`，取自拆分前的
`632b6076e847b3b1baa256c760e18f81a4821183`，覆盖媒体发现、HLS/DASH、问答证据与 QA/导出
OpenAPI 路径。独立测试覆盖模块无需导入主应用、可替换适配器、版本 1 历史兼容和新循环拒绝。
本阶段可独立合并/回滚；#143 的 Web/扩展拆分、JavaScript 依赖图、真实扩展与视觉验收仍需后续阶段。

经典界面 CSS 的后续小阶段见 [2026-10-09 拆分记录](ISSUE_ARCHITECTURE_CSS_20261009.md)：
末尾工作台密度、交互稳定性和学习控件共 658 行按原始顺序提取为三个同目录样式文件。

任务 ZIP 的独立小阶段见 [2026-10-09 序列化边界记录](ISSUE_ARCHITECTURE_ARCHIVES_20261009.md)：
三个 ZIP 格式的字节生成由显式类型输入驱动，路由与现有读取/渲染替换点保持在 `main`。
`main` 当前上限收紧到 4705 行，新增序列化模块计入原有 9250 行后端总预算；#143 继续开放。
`styles.css` 仍为 12,262 行，四文件合计仍受 12,920 行预算约束；精确快照、加载顺序和
桌面发行排除规则均有门禁。此阶段不代表 #143 已完成。

扩展当前页采集的后续阶段见 [2026-10-16 产品领域拆分记录](ISSUE_ARCHITECTURE_EXTENSION_DOMAINS_20261016.md)：
来源身份、请求归一化/持久化、Cookie 分区规划、本地后端传输和内容媒体提示拆为显式输入输出模块。
`background.js` / `content.js` 上限分别收紧到 1800 / 1850 行，全部新增依赖仍计入原有
335000 字节合计预算。权限、epoch、主动采集和交接编排保留在入口；导入模块不触发采集或网络。
该阶段不重新启用历史 page hook，也不替代最终组合树的真实扩展与长任务恢复验收。

## Recovery guidance projection (2026-10-16, #143)

`main.py` retains the existing `diagnostic_recovery_profile`,
`diagnostic_recovery_steps`, and `chaoxing_evidence_profile` entry points.
It reads saved inventory/preflight artifacts and validates local media, then
passes a `TaskRecord` and inert `RecoveryEvidence` into
`task_recovery_guidance.py`. That module imports only models: no filesystem,
network, API registration, task writes, or processor dependency. It returns the
unchanged recovery JSON, action order, privacy boundaries and user-facing text.
A shared action specification table replaces rebuilding all action labels
for each action. Media readiness is derived from task state and the supplied
existence check rather than allowing contradictory readiness flags.

Fifteen synthetic snapshots captured from e4ab6f1 cover running/failed,
DRM/MSE/blob, authentication/TLS/forbidden/manifest failures, fallback notes,
existing media, and Chaoxing evidence. The test checks complete JSON equality
and input immutability. Existing API/export tests continue to exercise adapters.
The entry-point budget drops from 4,705 to 4,270 lines; the new module is capped
at 451 lines and included in the unchanged 9,300-line extraction-group budget.
This stage can be reverted independently. It does not establish completion of
#143: app.js/styles.css/page_hook.js still need meaningful reductions, and
native UI/extension/long-task recovery evidence must match the integrated tree.

### Classic platform-evidence presentation (2026-10-16)

`web/platform-signals.js` owns the pure site-evidence projection and escaped HTML
for accessible media/request/iframe/preflight diagnostics. Input is an existing
plain task object; output is unchanged profile/header arrays and HTML strings.
It depends only on `LearnNoteTaskFormat`, loaded earlier in `classic.html`, and
has no DOM, storage, browser API, network or mutation side effects. `app.js`
retains event handlers and rendering orchestration through the same function names.
The complete original e4ab6f1 block (lines3047–3252) is preserved verbatim inside
the module; baseline block SHA-256 is
`9802d66e8339dd70e12391df2cca7bc115d97c9e2f825da706bc6cbe8ed5dc2c`.
Sixteen frozen original outputs cover absent/malformed profiles, frame0/null,
media kinds, request-body/header context, cookies/preflight and hostile text.
The tests also reject any browser-global access and task mutation. This is a
presentation boundary, not proof of real platform access or authorization.

The classic entry shrinks9455→9265 lines; the extracted module is214 lines.
The unchanged10100-line combined budget includes all five modules (10081 lines),
and the dependency/load-order guards include the new module. Revert the isolated
commit to restore the prior script and loader together. No task/API/export schema,
permission, remote request, or source-capture behavior changes.

`interrupted-task-reliability.py` adds a separate process-death acceptance gate:
synthetic local video plus timed subtitles runs through the real durable queue,
FFmpeg media processing, transcript/visual artifacts and `visual_ready`
checkpoint. The parent kills that worker without graceful shutdown. A fresh
worker runs the real FastAPI lifespan (staged-upload cleanup before recovery)
and must complete the same task
ID with identical media/transcript hashes and a final note. A context-required
queued intent must stop with `resume_context_required`; a repeated recovery
must dispatch nothing. Process IDs/exit status, intent sequence/generation, artifact mtimes, API read
and Markdown export checks, and checkpoint results are saved. Recovery currently
re-enters the local pipeline: matching hashes prove content preservation, not
avoidance of media/transcript/frame recomputation.
Only the external summarizer is an explicitly labeled deterministic fixture;
network calls fail closed, and no ASR/provider/authenticated-site/OS-power-loss
claim is made. The short script test runs when native FFmpeg is available;
Reliability CI separately requires the 3,600-second media case.

### Classic workbench override stylesheet (2026-10-16)

The existing contiguous `BiliNote-style workbench refresh` section and its later
workbench/cockpit/mobile refinements move from `styles.css` into the sibling
`classic-workbench-overrides.css`. It remains immediately after the base sheet
and before the previously extracted density/interaction/study sheets. No rule,
selector, declaration, whitespace, relative asset base or cascade order changes.
The original full-group SHA-256/byte/line snapshot is unchanged. The base shrinks
12,262→7,726 lines; the new sheet has 4,536 lines. All five sheets retain the
12,920-line aggregate cap and one cache version. Both native desktop specs
exclude these classic-only assets, including the newly extracted platform script.
This isolates the late workbench presentation layer; it does not remove legacy
overrides or claim that the active reader design changed.

### Classic transcript/window review projection (2026-10-16)

`visual-window-evidence.js` owns the pure subtitle/window overlap, cue selection,
summary fallback/deduplication, and review/checklist/question HTML functions.
Its explicit inputs remain window, transcript/segments, and optional cue limit;
its outputs are the original arrays, booleans and escaped HTML strings. It only
imports `fmt`, `escapeHtml`, `seekTimeButton`, and `seekTimeValue` from the pure
classic task-format namespace. The original nine function bodies are unchanged.
URL/media policy and visual-model evidence-state decisions remain in app.js,
as do every DOM update, event listener, selection and request lifecycle.

Fourteen frozen bb47c6f cases cover overlap endpoints, absent/negative timestamps,
summary priority and deduplication, transcript/excerpt/frame fallback, Unicode
truncation, hostile HTML and dense/empty cues. Tests reject browser access and
input mutation. Classic load order and dependency guards include the module;
both native specs exclude it with the rest of the classic-only UI. app.js drops
9,265→9,116 lines; the new module has 164 lines. The complete classic script
group remains under its unchanged 10,100-line limit. This extraction is
independently reversible and requires the existing hosted classic UI gate on
the integrated commit before claiming visual acceptance.
