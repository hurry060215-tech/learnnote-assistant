# LearnNote Browser Extension Store Listing

## Product name

LearnNote Current Video Assistant

## Short description

Send your current Chrome video to the local LearnNote app for source-linked notes and review.

## Detailed description

LearnNote is a local-first video learning assistant. This extension is the browser handoff layer for the LearnNote Windows desktop client.

Use it to:

- identify the video currently playing in the active tab;
- collect downloadable MP4, HLS, DASH, subtitle, iframe, and player-request evidence;
- verify that the selected media belongs to the visible page;
- send the selected page and media evidence to the LearnNote service running on `127.0.0.1`;
- open the corresponding task in the desktop client.

The extension does not record the browser tab. Video download, transcription, frame extraction, visual understanding, note generation, question answering, and exports run in the LearnNote client or in model providers explicitly configured by the user.

LearnNote does not bypass DRM, account permissions, paywalls, or learning progress controls. Only process content that you are authorized to access.

## Single purpose

The extension's single purpose is to identify the video currently playing in the active browser page and hand the media evidence to the user's local LearnNote desktop client.

## Category

Productivity

## Language

- Primary: Simplified Chinese
- Secondary: English (runtime strings and manifest metadata)

The extension includes Chrome locale resources in _locales/zh_CN and
_locales/en. Product UI follows the browser display language. Course titles,
subtitles, notes, questions, and imported text remain in their original language.
The extension hands authorized task evidence to the local workspace; remote
model use is explicitly configured in the client, not enabled by localization.
Unknown provider diagnostics retain their original wording.

- English support: [HELP.en.md](HELP.en.md)
- 简体中文帮助：[HELP.zh-CN.md](HELP.zh-CN.md)

The bilingual runtime, support text and four corresponding locale images have
repository acceptance evidence. Windows Edge passed all 18 locale/viewport/scale
conditions in [run 37941628048](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37941628048).
Codex inspected each replacement image and full-panel capture at original
resolution on 2026-10-09; the exact bytes and separate AI assistant review are
now [archived](store-assets/README.md). This is not store approval.

- English: [notes](store-assets/a400df83e450004253d6386847a1bfc5a473e00e/store-en-US-summary-1280x800.png)
  and [transcript](store-assets/a400df83e450004253d6386847a1bfc5a473e00e/store-en-US-transcript-1280x800.png)
- 简体中文：[笔记](store-assets/a400df83e450004253d6386847a1bfc5a473e00e/store-zh-CN-summary-1280x800.png)
  和[字幕](store-assets/a400df83e450004253d6386847a1bfc5a473e00e/store-zh-CN-transcript-1280x800.png)

See the [localization acceptance record](../docs/EXTENSION_LOCALIZATION.md) for
all six issue #144 criteria and the separate installation/permission boundaries.

Store images explicitly label separate rendered panel views and synthetic
course/service responses. They show the shipped UI with authored demo notes;
they do not claim a real model run or native extension installation. The same
original English lesson appears in both UI languages without translation.

## Support and policy URLs

- Homepage: https://hurry060215-tech.github.io/learnnote-assistant/
- Privacy policy: https://hurry060215-tech.github.io/learnnote-assistant/privacy.html
- Security policy: https://hurry060215-tech.github.io/learnnote-assistant/security.html
- Support: https://github.com/hurry060215-tech/learnnote-assistant/issues
- Source code: https://github.com/hurry060215-tech/learnnote-assistant
- Existing Chrome listing: https://chromewebstore.google.com/detail/learnnote-%E5%BD%93%E5%89%8D%E8%A7%86%E9%A2%91%E5%8A%A9%E6%89%8B/mncdchpkpikhacmkbanedpppcddapppe

The existing listing is recorded in the repository README and
[submission record](../docs/BROWSER_STORE_SUBMISSION.md). This asset preparation
does not verify or change its current published version or review status.

## Store review notes

1. Install and start the latest LearnNote Windows client.
2. Open a normal public MP4, HLS, DASH, Bilibili, or YouTube video page and start playback.
3. Open the LearnNote side panel.
4. The panel displays the current video, candidate count, duration, and media integrity state.
5. Click **Send to LearnNote**. The extension sends evidence only to `http://127.0.0.1:<local-port>`.
6. The local client creates the task and performs the remaining processing.

Authenticated-page testing requires a reviewer-owned account. LearnNote does not include test credentials or attempt to bypass site authorization.

## 简体中文商店文案

名称：LearnNote 当前视频学习助手

短描述：把当前 Chrome 视频交给本机 LearnNote，整理可回查来源的笔记与复习资料。

详细描述：在用户主动操作时读取当前页面的视频、字幕和媒体线索，并交给本机 LearnNote 客户端。可访问的视频由本机客户端下载，字幕、画面和笔记保存在本地。转写与模型生成的可用能力取决于用户安装的本地模型或主动配置的服务；外部模型调用遵循客户端配置。扩展不录制标签页，不绕过 DRM、付费墙或站点权限，不修改课程学习进度。

本轮面向已有 Google Chrome Web Store 条目准备素材，条目链接见上文；当前公开版本与审核状态不在本次素材验收范围内，不创建新条目或提交商店。截图明确标注并列展示的独立侧栏视图与合成课程、服务响应；示例笔记为预先编写，未实际调用模型或安装原生扩展。同一英文示例课程在两种界面语言下均保留原文，不含真实用户标题、Cookie、签名 URL 或个人资料。替换图片已由 Windows Edge 实际渲染，于 2026-10-09 经 Codex AI 助手逐张审阅，并连同原图、哈希与审阅记录归档；这是仓库双语素材验收，不代表商店批准或真实浏览器权限弹窗验收。
