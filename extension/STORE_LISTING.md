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
_locales/en. User video titles, subtitles, notes, and imported text are never
translated or uploaded by the extension.

## Support and policy URLs

- Homepage: https://hurry060215-tech.github.io/learnnote-assistant/
- Privacy policy: https://hurry060215-tech.github.io/learnnote-assistant/privacy.html
- Security policy: https://hurry060215-tech.github.io/learnnote-assistant/security.html
- Support: https://github.com/hurry060215-tech/learnnote-assistant/issues
- Source code: https://github.com/hurry060215-tech/learnnote-assistant

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

本轮只准备 Google Chrome Web Store 上架。正式 listing URL 在审核完成后填写，不以仓库链接冒充已上架地址。截图使用合成课程，避免真实标题、Cookie、签名 URL 或个人资料。
