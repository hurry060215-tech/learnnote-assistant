# 长任务、首个结果与恢复验收

- 日期：2026-09-24
- 本地代码基线：`origin/main` `e585b7fbf3067d19f19d68760ff4614ad2757efa`
- 本次 candidate 代码 commit：`84a16cb97663ad9e4e7e974b0fe84620bd87eb74`
- 关联 Issue：[#130](https://github.com/hurry060215-tech/learnnote-assistant/issues/130)、[#131](https://github.com/hurry060215-tech/learnnote-assistant/issues/131)、[#132](https://github.com/hurry060215-tech/learnnote-assistant/issues/132)、[#148](https://github.com/hurry060215-tech/learnnote-assistant/issues/148)、[#151](https://github.com/hurry060215-tech/learnnote-assistant/issues/151)

## 当前主线可靠性工作流

2026-09-24 手动运行 [Reliability gates #35960376745](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/35960376745)，目标为 `main` SHA `e585b7fbf3067d19f19d68760ff4614ad2757efa`，两项 job 和全部步骤通过。Freshness 报告确认 checkout 与预期 SHA 一致、工作区干净。离线 job 实际执行模型提供者无凭据合同、合成媒体/帧门禁、300/1800/3600/10800 秒矩阵、取消门禁、混合队列门禁及 3600 秒完整本地任务门禁；公共样例 job 使用无登录 Edge profile 探测 Samplelib MP4。

CI 归档：[离线可靠性报告](build/package4/remote-run-35960376745/offline/)，[公共样例报告](build/package4/remote-run-35960376745/public-audit/)。工作流完整步骤结论与检查时间保留在该 run 页面。

公共浏览器样例确认 cookie 数为 0，download-only task 成功在本机保存 2,848,208 字节 MP4，SHA-256 `8e68f504b0dbff5738741a1a377faa84baeb68b869ea52eaf7ec3d8154bb11ca`。`yt-dlp` metadata-only 探测也通过。这个路径证明了真实公开媒体下载和本地落盘；它没有运行 ASR。

## 当前 Windows checkout 的受控矩阵

在隔离目录 `build/package4`，用 FFmpeg 生成合成媒体并测媒体探测、抽帧和网格，不调用 ASR 或模型。每项均通过，资源预算为 RSS ≤512 MiB、剩余磁盘 ≥512 MiB。

| 时长 | 结果 | 峰值 RSS | 最小剩余磁盘 | 脚本耗时 |
| ---: | --- | ---: | ---: | ---: |
| 5 分钟 | 通过 | 39.5 MiB | 44,244 MiB | 1.312 秒 |
| 30 分钟 | 通过 | 39.4 MiB | 44,229 MiB | 5.735 秒 |
| 60 分钟 | 通过 | 39.7 MiB | 44,200 MiB | 10.391 秒 |
| 180 分钟 | 通过 | 39.9 MiB | 44,115 MiB | 28.750 秒 |

全部都是合成视频和帧抽取结果，**不是 5/30/60/180 分钟真实 ASR 转写通过**。

## 首个结果、取消与队列

- 隔离目录运行 60 分钟合成完整任务：总耗时 46.953 秒；`draft.md` 在字幕阶段完成后 0.015 秒可读；最终状态 `success`，checkpoint `note_ready`。输入是预制合成 SRT，summary 使用 `offline-fixture`，ASR 和模型调用都关闭。脚本现将转录结束到首个草稿 ≤5 秒作为可靠性门禁并把指标写进报告。
- 单独用 [Open Speech Repository American English 样本](https://www.voiptroubleshooter.com/open_speech/american.html) 的 `OSR_us_000_0010_8k.wav` 实测本机 faster-whisper `tiny` / CPU / int8：33.623 秒、8 kHz 输入，得到 10 段、407 字符，14.516 秒完成，远程 provider API 调用数为 0。该站要求引用 Open Speech Repository；本次只在隔离 build 缓存处理，未分发音频或模型。
- 180 秒合成媒体取消场景通过：取消延迟 0.063 秒，worker 退出，无取消后新增阶段。
- 本地 scheduler reliability 脚本通过 5 项混合任务：重型和轻量 lane 各最多 1 个并行任务，轻任务不被重任务阻塞，重复 enqueue 返回同一 future，journal 重开后状态保留。
- SSE 路由新增 HTTP 集成回归：组合 `Last-Event-ID` 与 `after` 游标只重放后续事件，保持单调 ID/中文消息，并在任务终态发出 `task_terminal`。

上述 ASR 样本是独立 WAV 解码，不是对 Samplelib 视频的识别，也不是 38 分钟 ASR 内存压力测试。ASR 测试报告、矩阵 JSON、资源报告和临时模型缓存都位于本地忽略目录 `build/package4`。

## 回归检查

Python 3.12.10 / Windows 的完整后端套件 608 项通过（96.0 秒），脚本套件 73 项通过。架构检查、i18n 审计、Markdown renderer、`node --check web/desk.js`、Python `py_compile` 与 `git diff --check` 通过。

## 仍需完成

- #130：当前 `main` 手动工作流已全绿，但合并后的 candidate SHA 仍需刷新一遍工作流再作为关闭依据。
- #131：上传限额/低磁盘/残留文件目前有隔离自动化回归，没有在真实低磁盘 Windows 盘和迁移数据目录做人工安装路径验收。
- #132：已验证队列 lane、5 项混合调度、取消和 journal 恢复；尚未在 3–5 个真实视频任务同时运行时测完整进程树资源上限。
- #148：5 秒首个草稿门禁只用预存合成字幕测量；公开媒体 download-only 和短 WAV ASR 单独通过，尚无带真实公开视频字幕的完整 5/30/60/180 分钟转写曲线。
- #151：HTTP SSE 游标/终态有集成回归，仍需桌面工作台真实断线重连、可见/隐藏资源行为、章节不跳顶及取消后的动态 UI 验收。

因此建议保留 #131、#132、#148、#151；#130 可在这条实现合并并对合并后的 main SHA 重新运行后关闭。不要把此报告里的合成媒体矩阵或离线 summary fixture 写成真实长视频 ASR 成功。
