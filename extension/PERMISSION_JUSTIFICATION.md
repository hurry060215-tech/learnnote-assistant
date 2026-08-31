# Browser Extension Permission Justification

LearnNote requests only permissions used by its current-video handoff purpose. The extension does not sell data, show advertising, or run product analytics.

| Permission | Why it is required |
| --- | --- |
| `activeTab` | Identify the tab selected by the user and run a fresh media inspection when the side panel opens. |
| `tabs` | Track navigation, title, URL, tab closure, and source identity so stale media from a previous page is not submitted. |
| `scripting` | Inject a fresh detector into the active page and its accessible frames when static content-script evidence is incomplete. |
| `webRequest` | Observe media manifests, video/audio segments, subtitle requests, and player API responses that are not exposed in the DOM. |
| `webNavigation` | Reset cached media evidence when the page or frame navigation changes. |
| `cookies` | On an explicit preflight/send action, read cookies for the page and selected media domains so the local downloader can access media already available to the user's session. |
| `storage` | Keep settings, handoff state, and a bounded 30-minute media-candidate recovery cache. Cookie and Authorization values are not stored in the candidate cache. |
| `alarms` | Expire old candidate and handoff state even when the side panel is closed. |
| `sidePanel` | Provide the current-video review and handoff interface without covering the video page. |
| `downloads` | Save an explicit diagnostic selected by the user. It is not used to download videos in the background. |
| `<all_urls>` host access | Video players, manifests, subtitles, iframes, and CDNs can use unrelated domains. Broad access is required to correlate the visible page with its media requests. |
| `127.0.0.1` / `localhost` | Check local LearnNote health, send the user-approved task, and open the task in the desktop client. |

## Data-use disclosure

Depending on the page and user action, the extension can process page URLs and titles, limited page text, player metadata, media/subtitle URLs, iframe URLs, request metadata, bounded player request bodies, and cookies for the page/media domains.

This data is used only to identify and retrieve the video selected by the user. It is sent to the local LearnNote backend when the user opens or reruns preflight, selects a resource, or sends the task. It is not sent to a LearnNote-operated cloud service.

The desktop client may contact video hosts or user-configured transcription and model providers. Those transfers are described in the public privacy policy.

## Chrome Web Store Privacy practices answers

Use the following values in the Developer Dashboard. Keep the dashboard
language set to **Chinese (Simplified)**.

### Single purpose

识别用户当前正在浏览或播放的视频页面，获取完成视频识别与交接所需的信息，并在用户主动操作后将该视频安全交接到本机 LearnNote 客户端。

### Data categories handled

- **Web browsing activity:** page URL, title, iframe URL, media URL, and
  selected media-request metadata. Used only to identify the video selected by
  the user and to prevent stale-page handoff.
- **Website content:** limited page text, player metadata, subtitle cues, and
  selected request evidence. Used only to identify and retrieve the selected
  video.
- **Authentication information:** cookies for the current page and selected
  media domains. Read only during an explicit preflight, candidate selection,
  or send action; passed to the local downloader to access media the current
  browser session can already access.

The extension does not sell data, run advertising or analytics, or send data
to a LearnNote-operated cloud service. The local client may contact video
hosts or model providers explicitly configured by the user; those transfers
are disclosed in the linked privacy policy.

### Remote code

**No, this extension does not use remote code.** All executable JavaScript is
included in the submitted package (`background.js`, `content.js`,
`page_hook.js`, and `sidepanel.js`). The extension does not load or execute
remote JavaScript/WASM, use `eval`, use `new Function`, or create remote script
tags. `chrome.scripting.executeScript` injects only the packaged `content.js`
or a small function literal defined in the packaged service worker.

### Limited Use certification

LearnNote uses the requested data only to provide the single purpose above.
Data is transferred only to the local LearnNote service or to a user-selected
video/model provider when required by an explicit user action. It is not used
for advertising, profiling, creditworthiness, or unrelated purposes, and it
is not sold or transferred to human reviewers.
