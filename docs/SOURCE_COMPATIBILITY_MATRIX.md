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


## 可见社区观点：独立的实验性入口

Bilibili 视频页的侧栏提供用户点击的“预览当前可见观点”。支持的范围是
HTTPS `www.bilibili.com` / `bilibili.com` 的 `/video/BV…` 或 `/video/av…`
顶层页面、有效数字分 P，以及已授权站点的已渲染评论正文/弹幕节点。
只读完整处于视口和祖先裁剪范围内的候选；不滚动、不请求新权限、不读取
作者档案、脚本状态或私有 API、不退回整页文本。上限为 20 条、每条
2,000 字符、合计 20,000 字符、遍历 1,500 节点。

这是合成 DOM fixture 定义的有限支持，不是当前线上全部 Bilibili 页面
兼容承诺。未知/隐藏/局部裁剪/覆盖/关闭 shadow root/iframe 内容会跳过。
无法读取时显示独立失败状态，不阻断原任务。原生权限与真实站点验收仍需
独立授权的人工证据；托管 Edge 的合成布局验收不能替代它们。

脱敏预览留在本地服务内存；只有逐条勾选并保存的内容进入独立观点库。
视频、分 P、标签页、任务和权限变化会使旧预览失效。它不产生课程事实、
语义聚类、观众总体频率/时间峰值或自动问答引用。详情与复现命令见
[社区观点快照验收](../ISSUE_COMMUNITY_CAPTURE_20261016.md)。
