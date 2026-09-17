# LearnNote 开放 Issue 分期台账

更新时间：2026-09-17
开放 issue 快照：32 个，来自仓库当前 GitHub open issues 列表。
正式基线：`v0.2.12`，`origin/main` 提交 `21ab344`（PR #187）。
本批收口台账：见 `docs/ISSUE_CLOSEOUT_0212.md`；实施分支：`codex/closeout-ad-0212`。

这份台账对应 #52。它记录当前代码证据、剩余缺口和验收边界，不把已经存在的函数、测试或界面入口直接当作 issue 已完成。0.2.12 已正式发布，但签名、真实站点、商店和跨平台条件仍单独记录，不因版本发布自动关闭相关 Issue。

## 状态说明

- 计划中：已纳入批次，尚未开始或尚无足够实现证据。
- 局部实现：已有可复用代码或本轮已落地一部分，但还不能关闭整个 issue。
- 待本地验收：主要代码已具备，需要真实浏览器、安装器、平台或完整场景测试。
- 外部条件：代码可以继续，商店账号、签名、公证、审核或真实站点条件单独阻塞。
- 关闭标准：整条 issue 的验收标准完成后才改为已完成；单个子能力通过不关闭 Epic。

## 分期总览

| 批次 | Issue | 当前状态 | 现有实现/证据 | 剩余缺口与验收证据 |
| --- | --- | --- | --- | --- |
| 贯穿 | #52 | 局部实现 | 本文件；README、CHANGELOG、docs/RELEASING.md 已有发布说明 | 每批更新版本、状态、失败证据和外部条件；不再使用过时的“全部完成”描述。 |
| A | #172 | 局部实现 | web/desk-product.js 已有流式助手、停止、草稿恢复和历史读取；本轮补 Enter/Shift+Enter、IME 防误发、单节点出处预览和原笔记绑定。 | 在真实工作台完成 10 次展开/收起、重复发送、中文输入法、历史消息、跨笔记来源、流式中停止和草稿恢复验收；没有额外模型请求。 |
| B | #55 | 待本地验收 | 更新中心已接入共享版本状态、24 小时检查、后台下载、真实字节进度、取消、官方来源/校验和、任务保护；安装前会保留程序快照并在安装失败或健康检查失败时回退。 | 安装版、便携版、磁盘/占用/断网场景和真实 Chrome/Edge 商店路径仍待验收；商店账号、审核、签名/公证是外部条件。 |
| B | #133 | 局部实现 | .github/workflows/desktop-release.yml 已固定 Actions SHA、锁定 Windows Python 依赖，并输出 SBOM、构建来源和 provenance 所需材料。 | 固定构建工具链、完整 provenance、SBOM 与实际发布包逐项复核；不能把“生成文件”写成二进制逐字节可复现。 |
| B | #134 | 待本地验收 | scripts/publish-release.ps1、校验和、draft release 复用和 release workflow 已有发布基础；更新包要求官方路径与 SHA-256，桌面更新写入安装日志和健康/回退结果。 | 断网、损坏包、磁盘不足、文件占用、真实失败恢复、回退版本和安全重跑需在候选安装包上验证。 |
| C | #130 | 局部实现 | .github/workflows/reliability.yml、scripts/long-video-reliability.py、scripts/cancel-reliability.py 已有周期可靠性门禁。 | 补“最新代码”发布约束、保留 5/30/60/180 分钟报告，并对周期任务失败、取消和重启恢复保留可审计证据。 |
| C | #131 | 局部实现 | backend/app/upload_limits.py、上传中间件和磁盘余量检查已存在；scripts/tests/test_resource_monitor.py 等覆盖部分边界。 | 并发上传总预算、残留文件清理、磁盘不足中断与恢复、多进程/重启场景仍待验收。 |
| C | #132 | 局部实现 | backend/app/task_queue.py 已有持久化意图、单工作者队列、取消和重启恢复测试。 | 轻重任务分流、公平排队、背压、残留 lease 和重启后不重复执行要以并发场景证实。 |
| C | #135 | 局部实现 | extension/manifest.json、extension/PERMISSION_JUSTIFICATION.md 已记录权限和按需捕获边界。 | 从 all_urls 到渐进授权的设计、Chrome/Edge 真实兼容、数据流可见性和拒绝权限后的完整路径。 |
| C | #143 | 局部实现 | backend 已按 downloader、pipeline、storage、study、routers 分出模块；当前工作台不再依赖旧前端。 | 以实际运行链路继续拆分，补模块边界、预算和回归，不为停用旧页面做大规模重构。 |
| D | #150 | 局部实现 | backend/app/text_cleanup.py、source_input.py、subtitle/transcript pipeline 已有 Unicode 清理、输入归一化和测试。 | 覆盖所有解码入口、原始字节保留、编码重选、乱码阻断和中英文正负样本；不得用清洗后的文本掩盖原始来源。 |
| D | #152 | 局部实现 | backend/app/note_document.py、markdown_structure.py、summary_diagnostics.py 已有语义结构和质量报告。 | 统一正文、目录、导出语义树；补重复内容、内部提示/系统提示泄露、失控 Markdown 和失败草稿检查。 |
| D | #129 | 局部实现 | backend/app/knowledge.py、transcript_passages.py、evidence_for_task 和助手 citations 已有字幕/文本证据。 | 每条结论稳定映射到字幕、画面或文档；至少 50 个中英文正负样本，单独报告误判、漏判和不能定位的回答。 |
| D | #139 | 局部实现 | web/desk.js 已有播放器、字幕 cue、时间定位和来源面板；本轮修正历史助手出处绑定。 | 统一问答、笔记、复习卡的来源定位；长字幕虚拟化，核验播放器/字幕/画面/笔记时间轴不会互相串源。 |
| D | #146 | 局部实现 | backend/app/model_route.py 和 /api/model/route 提供字幕、本地 ASR、远程文字/视觉路线与离线就绪度；工作台设置页显示路线、网络边界和阻塞原因。 | 真实模型权重准备、远程/离线切换和失败时延仍需在受控环境验证；没有凭据时不能把“路线可用”写成模型质量证据。 |
| D | #148 | 局部实现 | backend/app/pipeline_progress.py、task_queue.py、字幕优先模式和逐阶段状态已存在；docs/RELEASE_TEST_MATRIX.md 有长视频门禁。 | 在受控环境记录首个可用结果时延，补可恢复事件流、逐节草稿和 5/30/60/180 分钟资源预算。 |
| D | #149 | 局部实现 | backend/app/visual_pipeline.py、local_ocr.py、批量视觉窗口和视觉索引已有基础。 | 批量抽帧、OCR/视觉选择策略、减少视觉调用后的证据覆盖和失败恢复；不能只以请求数下降作为完成证据。 |
| D | #151 | 局部实现 | backend/app/events.py、observability.py、task events API 和 web 的 SSE/轮询回退已存在。 | 事件 ID、断线重连、去重、逐节草稿状态、旧任务读取兼容和重连后不重复渲染。 |
| D | #137 | 局部实现 | backend/app/range_learning.py、range API 和学习范围字段已有；播放器可以定位时间点。 | 扩展按当前位置/章节/选择区间交接，字幕和媒体按范围处理，并用逐项恢复状态完成验收。 |
| E | #138 | 局部实现 | backend/app/courses.py、playlists.py、课程页面和 playlist-preview 已有基础。 | 分P/播放列表批量确认、逐集队列、单集失败重试、逐集恢复、任务与课程状态一致。 |
| E | #157 | 局部实现 | backend/app/library.py、资料导入路由、PDF/Markdown/TXT/HTML 输入和 web 资料入口已存在。 | 文件预览、文档页码/段落定位、扫描 PDF 可选 OCR、资料与视频统一入口、导入失败可恢复。 |
| E | #140 | 局部实现 | backend/app/personal_notes.py、annotations API 和 web 我的补充已独立保存。 | 稳定锚点、重生成后的迁移、孤立批注修复、选择性导出和原文删除后的明确状态。 |
| E | #136 | 局部实现 | backend/app/study.py 有 FSRS 评分、计划、暂停和复习历史；web 有复习入口。 | 完整时区/DST、跨日边界、暂停/恢复语义与真实用户时区回归；统计区分阅读、答题、自评和稳定度。 |
| E | #141 | 局部实现 | backend/app/study_content.py、study.py 和助手 study.quiz 已有卡片/自测基础。 | 测验每题绑定证据、错题回看、掌握度计算和删除/重生成后的历史一致。 |
| E | #159 | 局部实现 | web 复习入口、study API、FSRS 和学习统计已有分散能力。 | 统一学习工作室入口，将卡片、测验、错题、进度和来源锚点串成一条完整闭环。 |
| F | #153 | 待本地验收 | web/desk.css、product.css、experience.css 已有阅读壳、响应式和深浅主题；UI visual workflow 覆盖中英文环境、390/768/1024/1440、200% 缩放、键盘与横向溢出门禁。 | 需要在本机启动候选工作台完成截图/键盘/减少动效复核；毛玻璃只用于外壳，正文保持实色高对比。 |
| F | #144 | 局部实现 | web/i18n.js 和部分中英文文案已存在。 | 桌面、网页、扩展和商店素材统一资源化；补漏翻译、动态状态、键盘提示和实际商店资产。 |
| F | #156 | 局部实现 | backend/app/document_exports.py 已有 docx/pdf、Markdown、bundle 等导出路径。 | 30 页以上长文档、图片、公式、引用链接、分页和失败重试；逐条来源锚点必须能回到输入证据。 |
| F | #142 | 局部实现 | 课程对照返回带 evidence_ids 的关键词关系；工作台显示可折叠 SVG 关系图，并保留每条关系可回查证据 ID 的列表替代视图。 | 关系仍是明确标注的关键词线索，不代表概念同义、因果或观点一致；需在结论锚点稳定后再做语义关系验收。 |
| F | #158 | 局部实现 | backend/app/community.py、社区观点设置和独立任务存储已存在。 | 显式采样、去重、删除、独立展示、事实/观点边界和导出隔离；不会自动抓取网站内容。 |
| F | #145 | 局部实现 | scripts/doctor.py、support-package、diagnostics 和本地数据边界已有。 | 首次使用诊断、用户主动导出的脱敏支持摘要、隐私说明与本地失败路径完成真实验证。 |
| F | #147 | 局部实现 | README、site、docs/RELEASING.md 和 readiness/audit 脚本已有产品说明与证据入口。 | 官网/商店只宣传已有证据；公开基准、样例输入输出、限制和真实安装路径需同步。 |
| G | #70 | 局部实现 | LearnNote.macos.spec、.github/workflows/macos-release.yml 和 platform docs 已有 macOS 构建基础。 | macOS 核心流程、迁移、升级和差异验收；签名、公证、Linux/ARM 只按真实可维护能力发布。 |

## 本轮已落地但仍未关闭的范围

- #172：助手输入和出处预览的代码修复、来源绑定回归契约已加入本分支；真实中文输入法、历史消息和 10 次重复交互仍待人工验收。
- #55/#133/#134：共享版本状态服务、更新中心入口、24 小时检查偏好、后台下载状态、取消、官方资产校验和任务/未保存内容保护已加入本分支；安装版、便携版、失败回退、真实 Chrome/Edge 商店仍未宣称通过。
- #52：本台账随每批提交更新。未在本地完成的功能不会通过文档措辞提前关闭。

## 外部条件

商店开发者账号、审核、签名/公证资质、实际 Chrome/Edge 安装路径和真实登录站点只阻塞对应验收，不阻塞其他本地代码批次。依赖 PR #166、#167、#168 单独维护：PDF 库升级走导出回归，Pydantic/Core 走配套版本约束，部署工具补丁走官网部署检查。

## 本地回归证据（2026-09-12）

- 后端完整回归在正确虚拟环境中修复 2 个 DST/时区统计缺口后为 561/561 通过；桌面端更新、健康检查、扩展安全解包和启动契约 42/42 通过；脚本/发布契约 60/60 通过。
- 扩展 53 个测试文件全部通过；Web 全量测试已通过，新增模型路线与课程关系图静态契约也纳入测试。
- 离线证据质量基准为 53/53，通过精确率和召回率均为 1.0；这只是固定夹具的门禁，不等同于真实课程事实质量评估。
- 已执行扩展打包和商店提交 preflight；没有提交商店发布请求。Chrome/Edge 商店安装、受管理解压版真实重载、签名/公证和跨平台实机仍保持人工待办。
# 当前更新（2026-09-17）

正式发布后的最新本地候选为 0.2.13 代码线，E–J 实现与浏览器回归见 [ISSUE_CLOSEOUT_0213.md](ISSUE_CLOSEOUT_0213.md)。0.2.12 的历史基线和开放 issue 台账仍作为发布前证据保留；未满足实机或外部凭据条件的 issue 不自动关闭。
