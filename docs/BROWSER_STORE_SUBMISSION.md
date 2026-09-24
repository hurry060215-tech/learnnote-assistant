# 浏览器商店提交材料

当前分发范围仅为 Google Chrome Web Store（2026-09-20 用户决定）。不安排 Microsoft Edge Add-ons 上架；Edge 的已有兼容代码可以保留。版本号必须与 `extension/manifest.json` 和本机后端一致。

## 产品说明

LearnNote 是面向个人学习者的本地优先视频知识助手。扩展只在用户打开侧栏并点击交接时读取当前页面媒体线索；视频下载、转写和笔记生成在用户本机后端完成，结果在浏览器工作台中展示。

## 权限用途

| 权限 | 用途 | 不做什么 |
| --- | --- | --- |
| `activeTab`, `tabs`, `scripting` | 读取用户当前明确选择的页面与播放器上下文 | 不扫描后台标签页，不自动录屏 |
| `webRequest`, `webNavigation` | 在用户触发采集时识别媒体请求、导航和播放状态 | 不上传请求体，不绕过 DRM |
| `cookies` | 用户创建任务时读取相关来源的授权 Cookie，以便本机后端重放 | 不持久化 Cookie，不发送到 LearnNote 云 |
| `storage`, `alarms` | 保存本地服务地址/短期配对 token、可过期的媒体候选缓存，维持本地心跳并显示已授权站点 | 不建立账号或云同步；撤销站点时清理该站点缓存 |
| `sidePanel`, `downloads` | 显示当前视频助手和用户主动下载扩展包 | 不后台下载课程 |

## 审核证据

- `scripts/e2e-extension-smoke.py --browser edge --debug-port 0`：真实 Edge、MP4/HLS/接口播放器、Blob iframe、学习通 mock。
- Chrome 自动化使用 Chrome for Testing，并通过 `LEARNNOTE_E2E_BROWSER` 指向其 `chrome.exe`；Chrome 品牌版自 M137 移除 `--load-extension`，M139 移除 `--disable-extensions-except`，不能再把旧命令行加载方式当作 Chrome Stable 回归入口。[Chrome 扩展开发说明](https://developer.chrome.com/blog/extension-news-june-2025)
- 自动 smoke 使用临时浏览器 profile 和本地 mock。它证明开发测试包的扩展/本机服务配对与页面到任务链路，不证明 Chrome Web Store 安装、商店审核或普通用户升级路径。
- `scripts/package-extension.ps1`：只打包 manifest、background/content/page hook、side panel、图标和安装说明。
- 扩展写请求需要本机短期 `X-LearnNote-Pairing` token；未配对请求返回 401。
- 侧栏“站点权限与数据流”列出额外授权的具体站点，并可撤销；撤销会清理该站点的页面状态、媒体候选和活动捕获 TTL。
- 公开隐私边界见 `PRIVACY.md`、`SECURITY.md` 和 `docs/PLATFORM_SUPPORT.md`。

## 提交前清单

1. 运行扩展 smoke、web/backend 全量测试和 `package-extension.ps1`。
2. 用当前 manifest 版本生成离线 ZIP 和 SHA-256；商店上传包与 GitHub Release 包必须相同。
3. 手工验证首次安装、侧栏打开、服务未启动、配对过期、来源登录态和拒绝 DRM 页面。
4. 截图不得包含 Cookie、签名 URL、真实课程标题或用户数据。
5. 审核说明明确：扩展不是录屏器，不提供 DRM/权限绕过，不代刷课程进度。

## 可选自动提交

`.github/workflows/store-submit.yml` 只接受手动触发。默认 `apply=false`，
只打包、校验并输出 SHA-256，不发起网络请求；只有同时显式选择 `apply`
和配置相应 secrets 才会上传草稿，`publish=true` 才会提交审核。

Chrome 需要 `LEARNNOTE_CHROME_ACCESS_TOKEN`、
`LEARNNOTE_CHROME_PUBLISHER_ID`、`LEARNNOTE_CHROME_ITEM_ID`。当前工作流仅允许 Chrome。缺少任意凭据时，CLI 返回
`blocked_missing_credentials`，不会尝试上传，也不会打印 secret 值。

2026-09-21 核对：README/官网已有条目 `mncdchpkpikhacmkbanedpppcddapppe`，不是要求新建条目。公开 listing 在当前网络工具中不可访问，实际审核状态与版本需从开发者后台确认。仓库 secret 名称清单未配置上述 Chrome 凭据；缺少的是自动上传配置及当前状态证据，不能据此判断用户没有商店账号。现有开发者模式验收不计作普通用户商店安装成功。

Chrome v2 上传按 [UploadState](https://developer.chrome.com/docs/webstore/api/reference/rest/v2/UploadState) 检查 SUCCEEDED；HTTP 200 不等于处理完成。异步上传通过 fetchStatus 有界等待，失败或未知状态不提交审核。审核提交使用 [STAGED_PUBLISH](https://developer.chrome.com/docs/webstore/api/reference/rest/v2/publishers.items/publish)，通过审核后仍等待单独正式发布，不自动公开。
