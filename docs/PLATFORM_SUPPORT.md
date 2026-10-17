# LearnNote 本地部署平台支持矩阵

这份矩阵是发布时的事实来源。`可用` 表示有自动化或人工验收证据；`预览` 表示接口/容器可运行但尚未达到桌面发行质量；`计划` 不代表当前版本承诺。

| 平台 | 浏览器工作台启动 | 本地后端/容器 | 浏览器扩展交接 | 数据目录与凭据 | 当前门槛 |
| --- | --- | --- | --- | --- | --- |
| Windows x64 | 可用：`start-learnnote.bat` 启动本机后端并打开默认浏览器 | 可用 | 可用：Chrome/Edge 真实 smoke | 可用：可迁移数据目录，凭据不写任务 | 需要用户授权浏览器页面和本地服务 |
| macOS arm64 | 预览：浏览器优先启动；未签名 `.app` 已有托管 macOS 原生启动证据 | 合成资料导入/导出、重启及个人批注恢复通过 | 浏览器连接协议可用；本机配对仍需单独验证 | 明确预览后的本机目录复制/重启通过；Keychain 路径存在，凭据不迁移 | 未签名/未公证；旧版应用配合升级前快照回退已验收，非新版数据库降级 |
| macOS x64 | 预览：浏览器优先启动 | 三系统契约不等于 x64 原生应用运行 | 连接协议与 arm64 相同 | 需平台验收 | 未提供 x64 原生应用验收证据 |
| Linux x64 | 预览：浏览器工作台；原生桌面集成未验收 | 源码后端合成导入/导出、重启及个人批注恢复通过；Docker 构建通过 | 浏览器连接协议可用 | 用户管理目录；模型密钥仅会话保存或由用户显式配置环境变量，无明文回退；完整任务迁移未验收 | 不承诺发行版级集成或可执行自动更新 |
| ARM NAS | 不提供桌面承诺 | linux/arm64 容器构建通过；NAS 运行与性能仍为预览 | 需用户明确配置可访问服务 | 用户管理挂载卷 | 多架构构建不代表 NAS 的 ffmpeg、模型和存储实测 |
| Docker (linux/amd64、linux/arm64) | 不适用 | 可用：compose/镜像构建 | 可用：浏览器连接用户明确暴露的本地端口 | 可用：挂载卷；不启用官方云同步 | 需要用户自行保护端口和反向代理 |

Linux 本地服务中的已选模型密钥只保留到服务退出；显式环境变量配置由用户管理，清除已保存连接不会删除该配置。详见[API 密钥隐私边界](../PRIVACY.md#api-keys)。

## 跨平台不变量

- 任务 JSON、`SourceEvidence`、资料库索引、导出 manifest 和脱敏资料包必须带 schema 版本，并能迁移或重建。
- 默认只绑定本机；Docker/反向代理部署必须显式配置认证，不因方便而扩大公开面。
- 浏览器采集始终按需触发；不加入后台录屏、DRM 绕过或课程进度代刷。
- 原视频、Cookie、签名 URL 和诊断秘密不得进入 sanitized bundle。

## 晋级门槛

各平台晋级必须保留 Windows 的任务恢复、来源适配、资料库、引用检索和导出契约。托管合成测试只覆盖报告列出的路径；Linux/ARM 的模型缓存、磁盘预算、取消响应和设备性能需要对应运行环境的实测。

The browser-first launchers do not require a native window or custom URI
protocol. The optional native packaging files remain in the repository for
compatibility, but they are not the recommended user path.

## Isolated native acceptance

`native-platform-acceptance.yml` is a separate, read-only-permission workflow
with no signing secrets or release publication. On macOS it builds and launches
the unsigned `.app`, confirms the native-window focus callback, and saves actual
runner screenshots. On Linux it launches the source backend; that lane does not
claim native desktop integration. Both lanes exercise UTF-8 document import,
byte-identical original export, missing/corrupt input failures, a separate
personal note, process restart, and backup restore into a fresh synthetic data
directory. Logs, screenshots and a machine-readable report are retained as CI
artifacts, including on failure.

Run the workflow and inspect its report/screenshots before citing acceptance.
The implementation of this harness is not a passing run. Restart is not
application-version upgrade or rollback. Signed/notarized distribution,
credential migration, extension pairing, real platform media, and native
updater rollback remain separate requirements. No user vault, provider key,
real browser profile or media-site account is used by this workflow.

## Verified migration and rollback (2026-10-17)

[Native run 38993618885](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38993618885)
on `ba068363ef9057b81e165657338a8741226941e4` passed both lanes. The macOS
arm64 frozen app additionally passed normal application Quit with backend/session
cleanup, stopped-source copy, destination-only known-path mapping, config-last
activation and a native restart using the selected destination. Original material,
content and personal-annotation exports were identical; source bytes, paths and
modification times were unchanged. The restarted owned window visibly lists the
imported material. [Exact evidence and limits](qa/20261017-native-data-migration.md).

[Platform run 38992754421](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38992754421)
on product-equivalent `25eafe0ad8bd96cefba9a0af2a78ea1dc3a237b7` passed the
Windows/macOS/Linux contracts, including 82 migration/lifecycle tests per lane.
[Windows CI](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38992754462)
also passed the offline backend suite containing copied foreign-task ownership
and export fixtures. This is bounded task compatibility, not automatic relocation
of external media or arbitrary foreign-library schemas. See the
[migration guide](DATA_DIRECTORY_MIGRATION.md) and
[task ownership boundaries](qa/20261016-task-path-portability.md).

The separate [native version rollback evidence](QA_NATIVE_VERSION_ROLLBACK.md)
proves old/new/old application execution with restoration of the pre-upgrade data
snapshot and retention of newer edits in a separate copy. It does not prove that
an old binary can read a newer schema. Native window Close, the actual native
settings bridge/folder dialog, credential transfer and macOS extension pairing
are not established by the Quit/helper smoke.

The separate `obsidian-native-acceptance.yml` uses a pinned official macOS
Obsidian release, checks its code signature, and runs only the repository's
compiled plugin in a disposable synthetic vault and isolated app profile. It
checks actual bundle import, rendered transcript-link navigation, regeneration,
personal edits, and immutable annotation-snapshot conflicts using real Obsidian
vault APIs and the local backend. It does not disable an OS/browser sandbox or
change an existing user's plugin settings. A passing native report and reviewed
screenshots are required; a built harness alone is not #140 acceptance, and
transcript navigation is not real-site video seek or reverse synchronization.

## Verified hosted baseline (2026-10-16)

[Native run 38938992009](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38938992009)
on `f39da5f2c2901be3a05b56c13458a448a29b13e0` passed the macOS arm64
unsigned application and Linux source-backend lanes. Reports and restart/restore
screenshots were inspected. The first-launch screenshot captured a loading
window, so it is not visual proof of first-launch readiness; startup/API checks
and the later rendered windows passed. The newer migration evidence above
supersedes this baseline for the paths it explicitly exercises.

[Container run 38973618230](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38973618230)
on `cdad6c49132f1b8640ec1330c33794fd1b1bb480` passed the existing
linux/amd64 and linux/arm64 build-and-publish job. This proves image builds, not
native ARM/NAS runtime performance.

The updater now exposes executable download/install actions only on Windows.
macOS/Linux show manual update guidance and retain the user-selected data
directory; a stale copied Windows receipt cannot enable executable actions.
This capability boundary does not establish application-version rollback,
credential migration, or complete cross-platform task/media relocation.
