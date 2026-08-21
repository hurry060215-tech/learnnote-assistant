# 来源兼容矩阵

矩阵只记录用户有权访问、可脱敏复现的路径；登录态真实课程不进入无人值守 CI。

| 来源 | adapter | 入口 | 已验证证据 | 常见失败分类 | 边界 |
| --- | --- | --- | --- | --- | --- |
| Bilibili | `bilibili@1` | 页面 URL、浏览器候选、yt-dlp | 真实/本地页面 smoke | `auth_required`, `no_media_found`, `drm_or_encrypted` | 只处理用户授权内容 |
| YouTube | `youtube@1` | 页面 URL、浏览器候选、yt-dlp | 兼容性契约与公开审计路径 | `auth_required`, `download_forbidden`, `yt_dlp_timeout` | 不绕过付费/DRM |
| 学习通/超星 | `chaoxing@1` | 用户点击后的浏览器交接、脱敏 mock | 本地 Chaoxing mock、真实人工登录态入口 | `auth_required`, `missing_playurl`, `missing_objectid`, `drm_or_encrypted` | 不进入无人值守 CI，不伪造课程进度 |
| 通用 MP4/HLS/DASH | `web@1` | DOM、performance、webRequest、page hook、直接链接 | MP4/HLS、POST API、Blob iframe、MSE fixture | `no_media_found`, `manifest_probe_failed`, `media_mismatch` | 只采集用户当前页触发的证据 |

## 失败分类不变量

- adapter 只负责来源身份、能力和诊断标签；下载器不因站点名称复制一套隐式分支。
- 任何候选进入处理前都必须经过预检或页面解析；失败必须保留错误码和主要恢复动作。
- 发现 DRM/加密信号时只能解释限制并建议本地导入，不能尝试解密或权限绕过。
- 新站点先加入脱敏 fixture、失败分类和真实人工验收，再进入默认兼容声明。
