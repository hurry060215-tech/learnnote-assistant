# LearnNote 云端验收快照，2026-10-12

状态：#329–332、#335 和 #336 已正常合入且各自适用主线检查通过。旧两小时测试失败。
修复主线的新独立两小时窗口已通过；旧失败与中断记录保持原结论。

产品版本：`912b0f30052c209e39178cd6a44d2fefe4bbf550`。本记录区分功能实现、合成输入验收和
真实平台/模型验收，不以工作流成功代替整条产品 issue 完成。

## 现在可以核对的界面与行为

运行入口与前置条件见 [README](../../README.md)。手工复核请使用独立测试实例，
将 `LEARNNOTE_DATA_DIR` 指向新的空测试目录，只导入新建的测试资料；备份恢复、
删除等操作也仅在该实例进行。本轮云端回归仅使用合成资料，没有操作真实用户资料。

| 操作 | 应看到的结果 | 已有证据 |
| --- | --- | --- |
| 展开/收起侧栏后阅读笔记 | 阅读栏在剩余空间中居中，左右留白对称；正文保持左对齐。移动抽屉关闭后没有残留大阴影。 | #324 的 1280/1440/768/390、光暗主题矩阵 |
| 打开全局助手，调整面板宽度 | 标题和操作按钮可读，来源独立成行。窄屏可滚动到说明、输入框和发送按钮。 | 实际 Edge 68 张截图；195px 仅是等效 200% CSS 回流 |
| 选中笔记后再次切换侧栏 | 桌面可见状态、按钮说明、aria-expanded 与 inert 一致；手机选择后关闭抽屉。 | #325 已由 #324 修复；桌面/移动实际交互 |
| 在源码回归入口 `/web/classic.html` 上传本地测试视频做预检 | 确认页保留媒体时长与完整性；整任务耗时显示未知。共享 HTTP 的 `estimated_seconds` 为 null；默认 desk 批量预检不显示此耗时字段。 | #326 / #327；实际生成媒体的 HTTP 测试；classic 页使用合成 metadata 的中英 Edge 确认流程 |
| 打开测试课程的删除确认页，不勾选子任务；另建测试课程复用相同媒体 | 默认只删课程分组并保留子任务；选择清理时保护共享/运行中的任务；复用保持稳定身份与证据。 | #249 已合入，实际 Edge 与后端磁盘/并发回归 |
| 导出和恢复学习备份 | 不完整或不兼容的备份清楚失败，原始字节保留；不能悄悄导出缺少个人内容的“成功”备份。 | #313 / #322 的实际 HTTP、文件与 Edge 错误/重试检查 |
| 使用有界多步助手编辑/导出或控制任务/课程 | 写入前可确认差异，有实际操作回执与读回；取消/失败停止后续依赖步骤。 | #303 / #304 / #310，实际 HTTP/磁盘与模拟结构化模型响应；未验证真实模型决策质量 |
| 编辑正文、目录、批注并打开出处 | 修订层与原资料分离；来源链接指向字幕、原文或画面；过期/歧义出处不冒充当前出处。 | 既有正文、目录、回源和个人锚点回归，随本轮 Edge 门禁继续运行 |

当前样式契约在仓库根目录 [design.md](../../design.md)，涵盖颜色、字体、间距、
组件和动态效果。用户参考截图尚未提供，因此这是当前基线与对齐修复，
不声称已经复刻某张参考图或完成新的视觉风格。原生 WebView、低端设备和
原生浏览器缩放也没有被这些 CI 截图覆盖。

## 本轮可复核证据

- [#324](https://github.com/hurry060215-tech/learnnote-assistant/pull/324)：最终
  `99a926efa2ab1aca531638691906eabe4f24cf41` 四组检查通过，CodeQL 零新增告警，
  无未解决评审线程。68 张实际 Edge 图逐张检查或与已审图做逐字节相同比较，
  最终页错误和外部请求均为零。
- [视觉截图包 `11761655317`](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38280084060/artifacts/11761655317)，76,635,007 字节，SHA-256
  `9024a980269ef0332bf5369dcd086c4758e63d13799e7d8e7a6e775d008a1f5b`，
  来自 [实际 Edge 运行](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38280084060)。
- #327 的本地完整回归：1,483 项离线后端测试、137 个 JavaScript 测试文件、
  178 项脚本测试（3 个既有平台跳过）。最终中英提示变化再次通过相应 Node、
  语法与架构检查；整合后的 JavaScript 文件再次全部通过。
- #327 当时主线 `8c23e596` 六组检查全部成功：
  [CI](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38285124523)、
  [可靠性](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38285124598)、
  [平台契约](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38285124564)、
  [CodeQL](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38285124608)、
  [实际 Edge](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38285124652)、
  [容器](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38285124532)。
  主线 Edge 再次运行中英预检与 68 视图门禁。
- [#327 最终 PR Edge 截图包 `11762158653`](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38284007493/artifacts/11762158653)，76,690,480 字节，SHA-256
  `6441ea345faaab63087e9860a582ab66579d2d5e645e6131402e69710ca0343b`，
  来自 [最终 PR 检查](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38284007493)。
  包内 `learning-ui/preflight-unknown.png` 和 `learning-ui/preflight-legacy.png`
  是两张已实际打开核对的中英文最终预检图；基线 68 图位于 `design-ui/`。
  Edge metadata 响应为合成夹具；
  实际生成媒体的 HTTP 暂存、时长和原字节保留由独立后端测试验证。
- #327 当时主线容器 `ghcr.io/hurry060215-tech/learnnote-assistant:sha-8c23e59` 已发布，
  清单摘要 `sha256:475b36b252b8850266e2c37062008fa803e4927f66d849e19b0ea76446bfc91c`。
  amd64/arm64 在构建中均实际执行合成 WAV 解码，PyAV 18.1.0；不下载模型，
  因此不把它称为真实语音识别质量验收。

## 有界模型主题章节：#330

[#330](https://github.com/hurry060215-tech/learnnote-assistant/pull/330) 的精确头
`931569c102fc7bcccdd417a28014f5ca71ed7698` 六组检查全部通过，CodeQL 零新增告警，
没有未解决评审线程；已正常合入 `acebfa6`，合并后的六组主线检查也全部通过。
本地通过 1,521 项离线后端、178 项脚本（3 跳过）、137 个 JavaScript 测试文件和
28 项桌面测试。独立复查通过 31 项流式专测及额外规范化/并发测试。

仅当用户选中准确的官方 OpenAI GPT-4.1 文本配置、来源为 1–3 个现有块且有
渐进回调时，同一个摘要请求才按完整主题章节逐步保存。其他服务、实际图文批次
及其失败回退、长来源递归请求继续原路径。每章显式待核对，最终笔记仍走原
事实门禁；既有 SDK 超时/前响应重试与最终修复成本边界见
[完整说明](../PROVIDER_STREAMED_CHAPTERS_20261012.md)。这不证明真实模型生成质量。

[实际 Edge](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38297569784)
通过五种渐进阅读场景，新增纯文字主题和无可用画面的图文请求两条路径。
10 张新主题截图已打开复核；页面、夹具、外部请求错误均为零。既有 68 视图
门禁通过，其中 67 张与已审基线逐字节相同，另 1 张已打开复核。
[最终截图/报告包](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38297569784/artifacts/11770150223)
为 77,892,742 字节，SHA-256
`461379542807a36ea2cb86c1d037970545bc4847c9f579aeba05eeab858ef16f`。
这些 Edge API/EventSource 为合成夹具，浏览器和页面是真实实现；独立真实 SDK
加 loopback HTTP/SSE 与磁盘测试确认第一章在第二章响应释放前已经持久化。

`acebfa6` 主线终态：
[CI](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38298720074)、
[可靠性](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38298720148)、
[平台](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38298720182)、
[CodeQL](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38298720203)、
[实际 Edge](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38298720141)、
[容器](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38298720200)均成功。
镜像 `sha-acebfa6` 的清单摘要为
`sha256:3508729ee790fba936e3b68189e16d0f05dc4ce50729513eab56d812c1bf0857`；
amd64/arm64 均实际通过生成 WAV 解码，未下载模型。

## 课程综合：#331

[#331](https://github.com/hurry060215-tech/learnnote-assistant/pull/331) 已于 20:46 UTC
合入 `9d2cd51c1da61c144740e5327096d7f9cae7501e`。精确头
`e3d16191aa5c9069be9f3bd68b1a6b3b7f5ffb8c` 六组检查通过，CodeQL 零新增告警，
没有未解决评审线程。默认课程检索仍返回本地摘录；新的独立入口须先预览
确切问题、原文与已选地址，再明确同意一次请求。最多六条索引原文、24,000
字符、3,000 输出 token；不完整扫描或超限概括明确拒绝，不能冒充完整课程总结。
所有综合推论保持待核对，固定出处也不代表一般事实正确。

本地实现回归通过 1,553 项离线后端、138 个 JavaScript 测试文件、178 项脚本
（3 跳过）与 28 项桌面测试；后续界面/夹具改动经重点复测与最终完整 CI。
独立复查及 32 项课程专测覆盖实际 loopback HTTP/SDK、来源与连接变更、
单次同意、错误/重定向/超时、源字节不变与扫描边界。模型是合成提供方，
未进行真实模型质量或收费验收。

[最终 Edge 运行](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38305468706)
的 [截图包](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38305468706/artifacts/11773091557)
为 79,397,438 字节，SHA-256
`f5573219e11d58aeb3b59c7d8ba0f9224d5faaeb5d5a3a32b65089814e9d5a1f`。
25 张课程截图与 68 张既有设计截图全部实际打开或与已审图逐字节相同：
最终包 89 张相同，四张变动图另行打开核对。新增界面覆盖四尺寸、光暗主题，
实际截图发现的超长引用裁切、同意框错位与窄屏标题折行已修正；无页面错误或
非预期请求。控件、字色、留白、阴影与动效沿用当前设计契约。

合并后 `9d2cd51` 六组主线检查全部成功：
[CI](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38306396095)、
[可靠性](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38306395965)、
[平台](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38306396046)、
[CodeQL](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38306395975)、
[实际 Edge](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38306396013)、
[容器](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38306396024)。
镜像 `sha-9d2cd51` 清单摘要为
`sha256:47bd0b7460575ffbd885471e1a0c7f34697b10586d38873de8b7641b0d80ce79`；
amd64/arm64 实际 WAV 解码通过，未下载模型。#138 的真实长课程质量标准保留开放。

## 小来源完整响应草稿：#332

[#332](https://github.com/hurry060215-tech/learnnote-assistant/pull/332) 在 1–3 个现有来源块、
非流式且无实际图文批次的既有单次请求中，收到明确 `finish_reason=stop` 后，
在原最终门禁前保存完整响应草稿。没有额外模型请求、人工章节拆分或延时；
未知/截断/过滤/工具调用结束不发布草稿。来源摘要、尝试与代际保持绑定，
始终显式待核对；投影写入失败不能让已成功的响应跳过原最终门禁，取消仍停止处理。

本地 1,568 项离线后端、178 项脚本（3 跳过）、28 项桌面测试及原 138 个
JavaScript 测试文件通过。首个实际 Edge 检查发现状态历史新增“已用”文字后
换行 19.1875px，使正在阅读的同一段向下移动。该失败未计为通过，也未放宽
3px 段落/标题位置边界。修复在每次同步状态渲染前后补偿实际高度变化，
避免覆盖用户的新滚动/导航，保留正文 DOM 和选区；新增生产状态/历史回归。
修复后本地 419 项合并 JavaScript 测试与 178 项脚本测试通过。
精确修复头 `df6c22de1c5bcdc47b5476c77dfbbc456c5af510` 的六组检查全部通过，
CodeQL 零新增告警且无未解决评审线程；独立复查的 14 项重点测试通过。
[最终实际 Edge](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38307732422)
通过六种渐进场景，修复后的同段位移为 0.1875px，正文 DOM/选区保留，页面、夹具及
非预期请求错误为零。30 张渐进截图中 17 张新增或变化图已实际打开，13 张与已审前版
逐字节相同；68 张设计图均与已审基线相同。
[最终截图包](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38307732422/artifacts/11773706546)
为 80,023,460 字节，SHA-256
`1fe94a12f35b1998a0becf2e05b43463bd52161a1cb4f5384d3415296fe03bcc`。
实际浏览器和页面不等于真实模型：API/EventSource 与模型响应为明确合成夹具。
已于 21:09 UTC 正常合入 `81cc8115b685ae5106b04aa8d8b9a20d1ebc14c5`，六组主线检查均已成功：
[CI](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38308877456)、
[可靠性](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38308877159)、
[平台](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38308877175)、
[CodeQL](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38308877451)、
[实际 Edge](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38308877200)、
[容器](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38308877170)。
镜像 `sha-81cc811` 的清单摘要为
`sha256:c4ac8876d004cef0efeea2ff485837470d3d6e94b476e999308ecb05d6405514`。
amd64/arm64 均实际通过合成 WAV 解码，PyAV 18.1.0，没有下载模型。
本页文档后续提交不改变产品代码；两小时冻结源至此版本的事件路由/存储代码相同。

## 当前处理尝试的耗时参考：#336

[#336](https://github.com/hurry060215-tech/learnnote-assistant/pull/336) 增加独立的
当前尝试计时，从已证实的本次入队（包含排队）或明确的处理入口开始，直到成功保存
笔记和本地检查。不能相加嵌套阶段耗时，也不包含之前重试、停机或用户确认等待。
区间依据本后端进程至少五个其他成功任务，匹配实际字幕来源、相近媒体时长、
设备模式、已选模型/选项、能力及复用路径；不够或不兼容时明确未知。
超出历史上界后停止显示剩余区间，不停在零秒或编造新的完成时点。

来源与处理路线只能在字幕就绪后确认，因此初始下载和转写期间仍不会猜测。
选定片段、本地 OCR、未知设备/能力、异常缓存或修复路径均保守排除；重启后
重新积累当前进程样本，旧证据文件保持原样。已有字幕后耗时参考仍保留独立标注。
这只是经验历史范围，不是经真实媒体校准的准确率，#148 仍开放。
完整边界、存储和隐私说明见 [本地耗时参考](../LOCAL_DURATION_ESTIMATES.md)。

本地通过 1,594 项离线后端、140 个 JavaScript 测试文件、178 项脚本测试
（3 个既有跳过）和 28 项桌面测试。独立审查覆盖来源隔离、排队边界、过期尝试、
链接/目标原字节保护及不延长凭据选项对象生命周期。最后平台测试修正后，
24 项专测再次通过；生产代码没有因平台测试修正改变。

精确头 `609d373f15cbd8387a00aed67e9e72e1842fb0c8` 的六组 PR 检查通过，CodeQL 零新增告警，
没有未解决评审线程。[实际 Edge 运行](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38318429950)
验证参考/超出历史上界/重试、阅读位置与选区，新增 1440/390px 光暗主题截图已打开核对。
页面资源和浏览器是真实实现，API/EventSource 是合成夹具；没有真实模型调用。
最终[截图和报告包](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38318429950/artifacts/11777998778)
为 80,245,351 字节，SHA-256 `d4fcefb9e1eebb4d5d4cfaa2447bb1d636f4da2999ce9752ff254fd151c9d348`。

早期 Edge 两次因新夹具的抽屉关闭控件和 resize 时序失败，Windows 完整测试
因链接目标的 `//?/` 原生表示与输入路径字面不同失败。这些失败不计通过。
夹具改用真实可见的侧栏关闭按钮，等待 resize/主题完成；软链接测试严格比较
操作前后的实际目标表示，仍检查链接、目标不存在或原字节保留，没有放宽断言。
课程取消/保留比较也只排除两个明确的实时观察时钟字段，其他全部数据继续比较。

合并后的六组主线检查全部通过：
[Platform contracts](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38319315152)、
[Container](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38319315070)、
[CodeQL](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38319314908)、
[Reliability gates](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38319315129)、
[CI](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38319315078)、
[UI visual acceptance](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38319315084)。
镜像 `sha-912b0f3` 清单摘要为 `sha256:4710703960c02b8ccfa3e5a2836067cbc9ab0ff2771c6c9d965d7b8b68c58131`；
amd64/arm64 实际合成 WAV 解码均通过，没有下载或调用识别模型。
之前 #335 已修复课程综合的 SDK 超时错误映射，相关离线回归及主线检查通过。
本次验收记录提交只更新文档，不改变已验收产品树或发布新的镜像。

## 有界两小时 HTTP/SSE

### 原窗口：未通过

原窗口 **未通过**。固定窗口为 16:05:14.898–18:05:14.898 UTC；到达终点后，
驱动在完整接收数组与磁盘事件比较处触发 AssertionError，退出码 1，18:05:22.983
完成清理。共 473 次连接、472 次计划断开、7 次干净重启、2 次心跳；自有服务
和写入线程均已停止。失败诊断和短测完成后另启新窗口，原记录没有延长或覆盖。

- [原始失败报告](20261012-event-soak-failed.json)与[独立磁盘核对](20261012-event-soak-assessment.json)：
  磁盘保留 7,093 条事件，其中 7,090 条生产事件的 sequence 从 1 连续到 7,090，
  没有保留窗口截断。报告中的 7,036 条、7,145.697 秒是最后一个定时检查点，
  **不是最终接收计数或完整运行时间**。原驱动没有保留失败时的接收数组，
  因此无法据此确定本次具体遗漏了哪些 ID。独立核对 JSON 中的 “No full rerun started”
  是新窗口启动前的历史诊断快照，不能解释为后续没有启动新窗口；原 JSON 保持不变。
- 独立两事件 fixture 在修复前主线复现了 [#328](https://github.com/hurry060215-tech/learnnote-assistant/issues/328)：
  初始事件页读完后，第二条事件先持久化，再检查到终态；旧流只发送 ID 1 就结束。
  [#329](https://github.com/hurry060215-tech/learnnote-assistant/pull/329) 在终态决策时复用
  既有跨进程任务事务重读状态/事件，出锁后发送，并再次检查重试/取消状态。
  普通状态读取与同步等待均移出 async 事件循环，避免锁竞争阻塞其他连接。
- 修复后[30 秒实际 HTTP/SSE](20261012-event-short-fixed.json)通过：1,448 条事件和
  完整持久化载荷相等、97 次连接、3 次干净重启、成功终态与进程清理。
  该短测没有触发心跳，不能据此声称修复后的长时心跳已验证。
- 将原合成事件文件复制到全新测试目录后，[实际 HTTP 重放](20261012-event-replay-fixed.json)
  通过全部 7,093 条及 Last-Event-ID=7090 的尾部三条逐载荷比较，原文件字节不变。
  本地修复提交 `9b966919` 与 PR `00f34fd3` 的树均为
  `478f0a65dd0ce8ad82022905f52044a00874f0ce`。

修复和短测不把上述两小时失败改为通过。此次保证是可读日志的已提交终态快照，
不保证任意生产者在终态后继续追加的事件，也没有改变既有日志读取失败映射。
终态 SSE 可创建既有 `.task-state` 协调锁；普通任务 GET/快照原字节合约保持不变。

这次测试使用生产事件路由和任务/事件存储，但服务是隔离的最小 FastAPI
进程，并非完整应用、原生扩展或真实模型服务。固定源版本为
`2424251996aa31dd668d0691773e86f8368aa2a8`。截至 `8c23e596` 的预检/界面变化
没有修改这些模块；#329 修改了事件路由；短测、重放与后续通过的新窗口另列。
原长测每秒写入合成事件，定期断开并以 Last-Event-ID 重连，每 15 分钟
重启服务，末尾核对全部事件 ID、完整持久化载荷和终态，并确认自有进程退出。
外部网络由仓库 guard 拒绝，模型调用数为零。

[实际执行的测试脚本](20261012-event-soak.py) SHA-256 为
`8f4dbf030aef491f239a0dbbb1be50e4682a056f62758d7fd17a1795dbecf93c`。
短测使用[只增强失败诊断的补丁](20261012-event-soak-diagnostics.patch)，保存最终接收
数组与计数；其驱动哈希为 `20bdaf59efd3c18c919bb797aac69cadbbadde7147e0787b0db4a114554e2b04`。
重跑时应使用固定源提交的独立干净工作树和全新的输出目录，不能指向既有应用
数据。脚本依赖仓库测试环境，不自动下载媒体或模型。固定参数是 7,200 秒、
每秒一个事件、每 900 秒干净重启、每 15 个事件断开；只有收到成功终态、
完整比较持久化载荷并完成进程清理后才算通过。最多等待终点后 60 秒接收终态，
这段宽限不是扩展测试窗口，也不自动重跑。

### 修复主线与新窗口：通过

[#329](https://github.com/hurry060215-tech/learnnote-assistant/pull/329) 已于 18:29 UTC
合入 `c31a507e`，#328 完成关闭。1,490 项离线后端测试和 178 项脚本测试通过
（3 个既有跳过）；14 项独立重点回归涵盖跨进程提交、事件循环锁竞争、分页、
取消/重试与只读快照。PR 精确头 `00f34fd3` 六组检查通过，CodeQL 零新增告警，
实际 Edge 的重连/游标终态和既有 68 视图门禁通过。

修复主线实际触发的五组检查全部成功：
[CI](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38291237563)、
[可靠性](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38291237546)、
[平台契约](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38291237534)、
[CodeQL](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38291237551)、
[容器](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38291237607)。
此次主线 UI 工作流的路径过滤没有触发，不能称为又做了一次主线 Edge；
实际 Edge 证据来自 [PR 精确头](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38290218044)。
新镜像 `sha-c31a507` 的清单摘要是
`sha256:86cab5d63cbc61ad7b5db5f4541d01b7c2c7c61d6acd86a0db2f1eaa2811679d`；
amd64/arm64 的实际生成 WAV 解码均通过，没有下载或调用识别模型。

新窗口固定为 **18:36:00.825–20:36:00.825 UTC**，冻结 `c31a507efdf9f38da9ba08e0bc1147d6c8d24731` 和独立测试目录。
窗口达到两小时后，在既定 60 秒终态宽限内完成比较与清理，20:36:12.305 UTC
退出码为 0。总执行时间含收尾为 7,211.476 秒；固定测试窗口没有延长。

- [终态报告](20261012-event-soak-fixed.json)：7,093 条事件，473 次连接、472 次
  计划断开、7 次干净服务重启、2 次心跳；成功终态已收到，自有服务和写线程均已停止。
- [完整比较](20261012-event-soak-comparison.json)：事件 ID 顺序与全部持久化载荷
  完全相同，遗漏/重复/意外 ID 均为空，首个载荷差异为 null。
- [独立只读复核](20261012-event-soak-independent.json)：7,094 条逐条 fsync 接收记录
  包含 7,093 条数据事件与 1 个成功终态，7,090 条生产 sequence 连续。接收 JSONL
  SHA-256 为 `e547c1824cb2bc4ada063a6abee5fba619084e2728c74bdbded432a76927adb2`；
  原磁盘事件 SHA-256 为 `08ded2ebbaa4f4c9f09cdbfd553d17f51991824026836fd0e31fbff2065c8199`。
  [独立核验脚本](20261012-event-soak-verify.py)另外核对两个原始文件、完整接收数组、
  单个终态、驱动哈希、源版本及清理标记。冻结工作树仍干净；服务日志仅有
  七次计划重启与最终清理的八条 SIGTERM 记录。

独立复核需要原始运行目录（含 `received.jsonl`、`received.json`、`report.json`、
`comparison.json` 和 `data/tasks/*/events.jsonl`），不能只用本页摘要 JSON 代替。
保存完整运行目录后，在仓库根目录执行：

```bash
python docs/qa/20261012-event-soak-verify.py --evidence-dir /path/to/fixed-two-hour --driver docs/qa/20261012-event-soak-durable.py
```

脚本明确接收两个路径，核对原始数据后写入运行目录中的
`independent-verification.json`；不会启动服务器或模型。

新[耐久记录驱动](20261012-event-soak-durable.py) 每条接收事件
均 flush/fsync 到独立 JSONL；结束比较保存缺失/重复/意外 ID、首个载荷差异，
再判断成功。失败或取消也保存最终计数、接收日志哈希与进程/线程清理结果。
驱动 SHA-256：`ed7b706e7a07b721d927ce91e1f7d66b5ab5ba83749f8b23e1d2bbb935753a75`。
使用同样的每秒事件/15 事件重连/900 秒干净重启参数；固定终点后最多 60 秒等待
终态，超时明确失败，不自动延长或重复。8 秒预检确认 389 条事件逐载荷相同，
主动停止预检确认已有接收记录保留且自有进程退出；预检也不是两小时验收。

历史 10 月 9 日的 115.6 分钟中断记录仍然是中断，不能被本次结果改写。
这次干净服务重启不等于硬崩溃恢复，也不验证模型提供方取消或 token 流。

## 原 18 项 issue 的剩余条件

### #151 按原验收逐项核对

原 issue 明确不要求所有模型支持 token streaming。以下把已有实现与真实缺口分开，
不因新增支持某个提供方就宣布整条完成，也不把原生权限流程追加为本条的独立标准。

| 原标准 | 当前证据和边界 |
| --- | --- |
| 单调 ID、断线重放、不重复 | 后端事件/事务测试、7,093 条真实 HTTP 重放、Edge 原生 EventSource 重连；固定新两小时窗口已逐载荷通过，范围见上文。 |
| 非 streaming 模型按阶段输出章节 | 成功视觉批次及长文字来源已有；短来源非流式为字幕提纲→单次完整响应→最终笔记，原先没有中间生成正文；独立 #332 已合入，1,568 项离线后端及最终实际 Edge 门禁通过；同一完整响应可在原最终门禁前显示为待核对草稿。不能靠额外模型请求或人工延迟制造渐进效果。 |
| 草稿/证据补充中/已验证三态 | 前两态已有；有来源依据的逐章节已验证转换缺失。当前 final-success 保留“生成完成不代表逐条事实已验证”，不会误升状态。 |
| 已完成章节可读、后续更新不跳顶 | 实际阅读器/侧栏 DOM、选区、滚动、前序插入与重放测试通过。 |
| 取消停止后续模型批次 | 文字/视觉/流式回归覆盖已完成草稿保留和后续批次停止；正在阻塞的 SDK 读取仍受既有超时约束，不承诺即时停止远端计算。 |
| 后端重启恢复 checkpoint/游标 | 新进程事件重放、持久队列/缓存/投影恢复已有；本页长测仅覆盖最小事件服务的干净重启，不等于完整应用硬崩溃或提供方计算恢复。 |
| 隐藏时降耗、恢复后同步 | 实际侧栏 DOM 门禁验证关闭流与恢复后显示新增章节；可见性信号由夹具控制。 |
| 动态内容 escape/sanitize | 侧栏字面渲染、Markdown 清理、恶意文本 Edge 场景和流式解析拒绝测试通过。 |

依据包括 `test_event_stream.py`、`test_progressive_sections.py`、
`test_text_chunk_sections.py`、`test_streamed_chapters.py` 与本页对应的精确 Edge 运行。
这张映射不把引用定位、生成成功或当前 `direct` 规则标签当成一般事实核验。

### 当前剩余条件

本次 #336 合并后再次核对，仍有 18 个开放 issue（排除 PR）；
新发现的 #325 / #326 / #328 / #334 已完成修复并关闭；
原产品 epic 保持开放。此时唯一未合入代码 PR 是不兼容依赖 #317。

| Issue | 当前已有 | 尚缺，不能据此关闭 |
| --- | --- | --- |
| #153 界面 | 当前视觉基线、对齐/侧栏/助手修复及真实 Edge 矩阵 | 用户参考图的最终风格验收、原生低端 WebView |
| #151 渐进事件 | 游标/重连、字幕和视觉批次草稿、阅读位置保持；#330 已合入官方 GPT-4.1 小来源章节流式切片，精确 CI/Edge 通过 | 有来源依据的逐章节“已验证”转换尚未实现。短来源非流式 #332 已补原响应待核对草稿；不要求所有模型 token streaming，不能以生成完成替代核验 |
| #138 课程 | 分集队列、恢复、去重、删除选择、课程范围证据检索 | 默认回答仍是原文摘录；独立 #331 已合入有界综合，精确 CI/Edge 与独立复查通过；真实长课程质量未验 |
| #142 概念图谱 | 引用式图/列表、过滤、手工概念拆分合并、索引恢复 | 当前关系为关键词共现；一般语义共识/冲突/推断生成未实现或验收 |
| #148 时延 | 阶段埋点、渐进结果、字幕就绪后的历史区间；#336 新增当前处理尝试的独立整段计时与同进程兼容历史参考 | 字幕来源等实际上下文就绪前仍未知；选定片段、本地 OCR、重启后或样本不足不估算；真实媒体/设备/提供方预测准确度未验，原完整标准保持开放 |
| #149 OCR/性能 | 本地 OCR、批处理、媒体身份和可恢复缓存 | 原四小时视频对照、长片预算与模型调用减少且不损失事实覆盖的实测 |
| #140 个人内容 | 独立批注、锚点修复、完整导出、事务恢复保护 | 真实 Obsidian 宿主同步、安装升级生命周期 |
| #139 同步回源 | 本地播放器/字幕/结论/画面联动和身份保护 | 原网站扩展跳转、真实授权切换及原四小时视频 |
| #146 模型路线 | 能力说明、离线就绪和有界兼容回退 | 有依据的费用/耗时区间、上下文/图片能力限制仍不完整；另需已配置服务与费用上限下的真实兼容/质量/费用验收 |
| #129 事实证据 | 引用模式、可点击导出、规则门禁、正反例；候选定位与支持判定分开报告 | 固定 60 条语料直接支持召回仍为 0.50；12 来源混排中正确候选命中 23/24 条支持陈述、11/12 条释义，不证明语义支持。单课历史 0/5 为带人工时间提示的直接支持结果，非无提示检索评估；另缺真实模型实体/数字/否定质量。详见[候选定位补充](../CLAIM_EVIDENCE_BENCHMARK_20260924.md#2026-10-13把候选定位与支持判定分开测量) |
| #147 对外定位 | 公开资料、验证方法和当前合成界面示例 | 真实质量基准、用户理解与商店材料一致性；不能发布无依据优势 |
| #143 架构 | 模块/依赖循环/体积边界门禁 | 原单体明显缩减目标未达到：page_hook 2,825→2,851、content 2,101→2,176、app.js 9,641→9,455；上限门禁不等于已缩减，不为清零冒险重写 |
| #137 当前页面 | 范围与来源身份、复用、证据边界回归 | 实际 Chrome/Edge 来源页捕获与跳转、明确授权的原生权限流程 |
| #135 权限体验 | 渐进权限/数据流说明与回归 | 原生安装、授权、撤销、重新配对；不得静默开启开发者模式或权限 |
| #55 发布 | 打包、校验、兼容检查及历史 Chrome v0.1.55 上架记录 | 当前商店版本和普通安装/升级未核；Edge 兼容/原生 QA、Windows 签名仍待验。旧发布指南为 Chrome-only，是否新增 Edge 上架及所需账号配置尚需明确 |
| #70 macOS | 可移植契约、双架构容器与真实 WAV 解码 | macOS 原生核心流程、签名/公证、凭据存储、迁移/回滚 |
| #158 社区输入 | 手工内容导入、隔离/脱敏、删除/导出 | 自动 Bilibili 评论/弹幕采样适配器未实现，官方允许路线/授权/条款尚待核实 |
| #52 路线图 | 跟踪上述目标 | 依赖验收未完成，不能把路线图关闭 |

#148 的完整字幕参考门禁已经覆盖 5/30/60/180 分钟、每组 20 次；不是没有
基准集。对应 [可靠性运行](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38272666635)
的提纲 p95 为 0.125/0.172/0.219/0.407 秒。它运行真实本地队列/存储/草稿路径，
最终摘要采用确定性测试适配器，因此不能代表真实模型质量或下载/ASR 耗时。

以上召回指标的范围见 [60 条固定语料](../CLAIM_EVIDENCE_BENCHMARK_20260924.md)与
[小样本公开课程审计](../REAL_COURSE_CLAIM_AUDIT_20260924.md)，不能外推为一般准确率。

真实质量验收仍缺可读取的原视频/原字幕、已安全配置的模型连接和费用上限。
既有网页时长观察与播放能力不能替代全片验收；尚无原片全片通过结果。
本轮未配置或传输模型凭据，没有进行模型调用，也没有将模拟响应计作真实模型结果。

依赖 PR #317 继续保留：PyAV 19 与当前 faster-whisper 解码接口不兼容，
不能仅为升级而跳过依赖约束或改变音频处理。其余新依赖及 CI 锁定修复已
经过精确检查与正常主线合并。
18:52 UTC 重新核对，[PyPI 当前发布](https://pypi.org/project/faster-whisper/)与
[上游最新 release](https://github.com/SYSTRAN/faster-whisper/releases/tag/v1.2.1)仍是 1.2.1。
上游已记录[同一 PyAV 19 参数问题](https://github.com/SYSTRAN/faster-whisper/issues/1589)
并提供源码修复，但未将它视为本项目已验证的稳定包；当前继续保留可正常解码的版本边界。
