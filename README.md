# LearnNote Assistant

BiliNote-style browser learning assistant for direct current-page video extraction, local video upload, transcription, frame-grid visual understanding, and Markdown note generation.

This project intentionally does **not** record the browser tab and does **not** bypass DRM, login, or course progress systems. It downloads media only when the current page exposes a normal accessible URL, HLS/DASH manifest, yt-dlp supported page, or a cookie-authorized resource visible to the active browser session.

## Features

- Chrome/Edge MV3 extension with a Side Panel.
- BiliNote-style workspace UI: source selection, processing options, task history, note/transcript/frame/diagnostic result tabs.
- Richer BiliNote-style reading workspace with task search/filter, status counters, Markdown rendering, frame-grid preview, and failure recovery hints.
- BiliNote-style task stage rail for download, transcription, frame slicing, note generation, and completion.
- Bilibili link entry accepts a full B站 URL, bare `BV...`/`av...` ID, or copied text containing one; the backend normalizes it to a video page, downloads through yt-dlp, merges separate audio/video with the project ffmpeg, and replaces the placeholder with the real video title.
- Transcript timeline view aligns each subtitle segment with its frame-grid visual window, so notes can be reviewed by time slice instead of as a flat transcript.
- Web UI subtitle timestamps and visual-window checkpoints can seek the local `media.mp4` preview for time-anchored review.
- Markdown note export from both the local Web UI and the browser Side Panel.
- Task audit export from both UIs: a Markdown report of the direct-extraction route, stage gates, reuse readiness, recovery recommendation, and privacy boundary.
- Study bundle export from both UIs: Markdown note, `audit.md`, diagnostics, task metadata, transcript JSON, visual-window index, frame-grid screenshots, and a redacted machine-readable `manifest.json` in one zip.
- Standalone manifest export from both UIs for the current task route, audit gates, media evidence, transcript/visual-window counts, and artifact list.
- Current-page media detection from DOM, all-frame content scripts, Performance entries, and `webRequest`.
- `webRequest` captures media candidates as soon as response headers arrive, so long-running video/range streams do not have to finish before they can be selected.
- Main-world fetch/XHR hook for media URLs exposed in text, JSON, playlist, or script responses before they appear in `<video>`.
- JSON/HTML script media-field discovery for extensionless player APIs such as `hls`, `dashUrl`, `playUrl`, or `videoUrl` when sibling metadata or field names identify HLS/DASH/video content.
- Runtime page-global player config discovery: common globals such as `lessonPlayerConfig`, `coursePlayerConfig`, `ananasVideoInfo`, and `__playInfo` are watched even when assigned after extension injection, so late SPA/player setup can still expose mp4/FLV/HLS/DASH candidates.
- URL-encoded and base64-wrapped media field values are decoded during page scanning and main-world response inspection.
- Blob/MSE-backed player recovery: when a page fetches an accessible media response as a `Blob`, `ArrayBuffer`, or `ReadableStream` chunk, constructs a `Blob`, or appends the buffer to a `MediaSource`/`SourceBuffer`, the extension maps that generated `blob:` playback URL back to the original mp4/FLV/HLS/DASH request and ranks it as the current video candidate.
- Backend page scanner for manually pasted page URLs, so the local Web UI can try direct media extraction before yt-dlp fallback.
- Backend page scanning also decodes JS-escaped bare media URLs such as `https:\/\/...m3u8` even when they are stored in generic player variables rather than obvious `videoUrl` fields.
- Manual URL tasks can explicitly force a pasted extensionless link to be treated as a video file, HLS manifest, or DASH manifest instead of only relying on suffix detection.
- Manual URL tasks in the Web UI can preflight direct media links before task creation and can run download-only mode to save an exportable local `media.mp4` without transcription or summarization.
- Iframe/player-page fallback: when the top course page is only a shell, the backend also tries the active frame URL, candidate page URL, Referer, and initiator as page-scan and yt-dlp fallback targets.
- Backend player-iframe scan: when a manually pasted or browser-sent page only contains a course/player iframe, the backend follows that player frame with the page's browser context and scans it for mp4/FLV/HLS/DASH URLs before falling back to yt-dlp.
- EME/DRM signal detection: the extension records `encrypted`, `setMediaKeys`, and `requestMediaKeySystemAccess` evidence so encrypted pages fail with a clear reason instead of pretending a normal direct URL was missed.
- Cookie handoff from the current browser session to the local backend at task start.
- Cookie handoff includes the top page, active media URL, player iframe URLs, candidate page/frame URLs, initiator, Referer, and Origin domains so iframe-based course players keep their browser session context.
- Non-sensitive browser request headers such as `Referer`, `Origin`, `User-Agent`, `Accept`, `Accept-Language`, `Sec-Fetch-*`, `Sec-CH-UA*`, and `X-Requested-With` are captured for media candidates and reused by backend downloads.
- Bounded text/form POST bodies from recent playback-related XHR/fetch requests are kept in extension memory and handed to the backend only with the selected task, letting JSON play APIs be replayed locally to resolve the real media URL.
- Local FastAPI backend on `127.0.0.1:8765`.
- Download order: selected browser/media candidate first, then yt-dlp page resolver fallback with the current browser session's cookie file and safe request headers.
- Download diagnostics: every task records the direct-file, manifest-ffmpeg, skipped blob/fragment, and yt-dlp attempts with status, HTTP code, content length, output file, and failure reason.
- Direct-file downloads reject HTTP 200 login/error HTML bodies before they enter the media pipeline, so expired cookies fail as `auth_required` instead of becoming confusing ffmpeg processing errors.
- Local video upload from both the Side Panel and the local web UI.
- Shared processing pipeline: normalize every downloaded or uploaded video into project-local `media.mp4`, extract audio, transcribe, slice frames, build frame grids, generate a visual-window index, summarize.
- Multimodal LLM summaries run in visual-window batches and then merge the local window notes into the final Markdown note.
- Browser subtitle cues, page subtitle tracks, yt-dlp platform subtitles (`.vtt`, `.srt`, `.ass`, `.ssa`), and embedded text subtitles are preferred over Whisper when available.
- Structured failure codes: `no_media_found`, `auth_required`, `drm_or_encrypted`, `download_forbidden`, `unsupported_manifest`, `processing_failed`.

## What Works Now

- Paste a B站 URL or `BV...`/`av...` ID into Web UI **链接解析**, then choose **生成链接笔记**, **预检链接**, or **只下载到本地**. YouTube and other yt-dlp-supported page URLs use the same entry.
- Direct current-page task creation from the extension Side Panel.
- DOM, iframe-aware content scripts, Performance, active `<video>` state, and `webRequest` resource discovery.
- Page-network hook discovery for mp4/FLV/HLS/DASH/subtitle URLs embedded in fetch/XHR text responses. The hook also records Blob object URL, fetch stream chunk, and MediaSource source mappings when the page builds playback from accessible media responses; it does not record playback or inspect binary video payloads.
- Page-global player config discovery: the page hook scans bounded common globals such as `__playInfo`, `playerConfig`, `videoInfo`, `lessonPlayerConfig`, and matching video/player/media keys for mp4/FLV/HLS/DASH/subtitle URLs, including encoded fields and late runtime assignments, without recording playback.
- Extensionless manifest-body discovery: if a player endpoint such as `/api/play?lesson=...` returns an HLS/DASH manifest body with a generic MIME like `application/octet-stream`, the page hook promotes the response URL itself to a direct HLS/DASH candidate.
- Backend page-text scanning for manually submitted URLs: HTML/JSON/script responses are scanned for absolute or relative mp4/FLV/HLS/DASH/subtitle URLs before yt-dlp is tried.
- Extensionless API URL scanning: JSON fields or inline script fields like `hls`, `dashUrl`, `playUrl`, and `videoUrl` can become candidates even when the URL is `/stream?lesson=...` instead of ending in `.m3u8`, `.mpd`, `.flv`, or `.mp4`.
- Extensionless browser media request capture: if Chrome reports a `webRequest` as `media`, the extension keeps it as a direct video candidate even when the URL is `/play?id=...` and the server only returns a generic MIME type.
- Frame-aware context aggregation: the extension asks every reachable frame for page text, active video state, and media resources before ranking candidates.
- Frame-aware fallback download: if the outer page cannot be resolved, backend page scanning and yt-dlp fallback are retried against the detected player iframe, candidate page URL, Referer, and request initiator.
- Course-shell fallback: backend page scanning can now follow obvious player iframes from a shell page and reuse the iframe URL as Referer for media discovered inside that player page.
- Dynamic SPA video detection through MutationObserver, media event binding, periodic rescans, and PerformanceObserver resource updates.
- Cookie collection at task start/preflight for the page URL, active frame URLs, resolved/redirected media URLs, request initiators, and media domains. On browsers that expose partitioned-cookie APIs, the extension also asks the active tab/frame for the matching partition key before syncing cookies.
- Browser-context download replay: direct media, subtitles, ffmpeg HLS/DASH merges, and yt-dlp page fallback reuse safe request headers plus the task-start cookie jar where applicable. Captured `Cookie` and `Authorization` headers are never replayed from request metadata; cookies are synced only through the explicit task/preflight handoff.
- POST playback API replay: when the browser reaches a `/play`/`stream` JSON endpoint through a text or form POST, the extension can hand its bounded request body to the backend so preflight/download resolves the embedded mp4/FLV/m3u8/mpd URL instead of retrying the endpoint as a plain GET.
- JSON playback endpoints with multiple embedded source URLs are preflighted in order, so an expired or forbidden first source can be skipped when a backup mp4/FLV/HLS/DASH source is still reachable.
- Browser-context preflight: selected mp4/FLV/HLS/DASH candidates can be checked with a small local backend probe before the full download. The result reports strategy, HTTP status, MIME type, content length, bytes checked, safe request-header names, and structured failure codes.
- Side Panel task start now preflights ranked direct-download candidates in order and automatically switches to the first reachable mp4/FLV/HLS/DASH resource, so a stale or forbidden top candidate does not stop the workflow when another visible media URL works.
- Side Panel also has a download-only current-page action: it uses the same preflight, cookie handoff, direct downloader, manifest merge, and yt-dlp fallback, then saves an exportable local `media.mp4` without transcription, slicing, or summarization.
- Download-only tasks retain browser/player subtitle cues, so `继续切片总结` can reuse already captured subtitles instead of falling back to ASR.
- For players that render captions only as visible DOM overlays, the extension keeps a bounded in-page subtitle history while the lesson plays, instead of only sending the single caption currently on screen.
- Main-video ranking based on the actively playing `<video>` first, then the largest visible video element.
- Candidate evidence from `webRequest`, including request type, HTTP status, MIME type, content length, initiator, and frame id when available.
- Long-running media responses are added from `onHeadersReceived`, then merged again on completion if the request later finishes.
- Playback-aware candidate ranking: the Side Panel boosts exact current `<video>` sources, same-frame media requests, recoverable Blob/ArrayBuffer/ReadableStream/MediaSource source mappings, and recent requests from Blob/MSE-backed players before starting a task.
- DRM-aware failure boundary: if a page triggers EME/DRM signals and exposes no downloadable mp4/FLV/HLS/DASH candidate, the task fails early as `drm_or_encrypted` and keeps the key-system/init-data evidence in diagnostics.
- Recoverable fragment URLs such as `.../master.m3u8/segment.ts` or `.../manifest.mpd/chunk.m4s` are promoted to inferred manifest candidates.
- Plain `.ts` / `.m4s` fragment clues near the current playback can also trigger a sibling manifest preflight (`master.m3u8`, `index.m3u8`, `manifest.mpd`, etc.) before the app gives up on direct extraction.
- Subtitle discovery from `<track>` elements, Performance entries, and `webRequest`.
- Direct video download for exposed MP4/FLV/WebM/MOV/MKV URLs.
- HLS/DASH manifest download through ffmpeg when a manifest URL is visible.
- yt-dlp page URL fallback for supported websites when direct browser resources are not usable.
- Local video upload from the extension and the local web UI.
- Shared video processing: remux/standardize local and downloaded videos to `media.mp4`, extract audio, transcribe with local `faster-whisper` or OpenAI-compatible/Groq ASR when selected, extract frames, keep periodic visual anchors even on static slides, generate frame grids, and emit Markdown notes.
- Transcript priority: browser/player subtitle cues first, page or yt-dlp platform subtitle second, embedded text subtitle third, then selected ASR engine fallback.
- Configurable slicing: frame interval, grid layout, ASR model, and note style.
- Web UI and Side Panel diagnostic tabs show the selected resource, browser evidence, and every backend download attempt.
- Web UI and Side Panel task actions can export `audit.md` separately, and the zip bundle includes the same report so direct extraction evidence remains portable.
- Side Panel direct-extraction console shows whether the selected candidate is a downloadable file, HLS/DASH manifest, subtitle, blob clue, or fragment clue, plus reused request-header names and request evidence.
- Side Panel has an explicit direct-extraction preflight button: it syncs cookies only when clicked and asks the local backend to verify whether the selected candidate is actually reachable before starting the full task.
- Side Panel also runs that reachability preflight automatically before `总结当前视频`; if every direct candidate fails but the current page has a normal HTTP(S) URL, it still creates the task so backend page scanning, iframe fallback, and yt-dlp can continue. Pages with no usable page fallback keep the local upload fallback visible.
- Full HLS/DASH downloads repeat a backend manifest probe before invoking ffmpeg, so expired-login HTML or DRM markers return structured `auth_required` / `drm_or_encrypted` errors instead of a generic merge failure.
- Side Panel supports a local video drop target as the non-recording fallback when the current page only exposes unrecoverable blob/fragment clues.
- Diagnostics also show which safe request-header names were available for a selected media candidate without exposing cookie or authorization values. Persisted task debug files redact cookie values and browser request-header values.
- Blob and media-fragment requests are kept as diagnostic clues instead of being hidden, but they are not treated as independently downloadable video files.
- Extensionless Performance resource entries initiated by `<video>`, `<audio>`, or subtitle tracks are kept as media candidates, so `/play?id=...` style URLs are not missed only because they lack `.mp4`, `.flv`, or `.m3u8`.
- Recent byte-range media requests near the active playhead are treated as stronger evidence for the currently playing video, which helps avoid selecting ads or background preloads.
- Current-page tasks retain the active player snapshot used at task start, including playback time, duration, frame id, dimensions, source URL, and DRM marker for later diagnostics.
- Task records retain the frame interval, grid layout, ASR model, note style, and visual-understanding setting used for that run.
- Multimodal prompts are organized by frame-grid windows, pairing each visual slice with the transcript segment from the same time range. Long videos are summarized in batches so later frame grids are not silently dropped.
- Task diagnostics record whether the note came from a vision LLM, text LLM, or the local frame-index template, including the downgrade reason when the model call is unavailable.
- Each completed video task writes `visual_index.json`, exposes `/api/tasks/{task_id}/visual-index`, and returns `visual_windows` in the task record so the UI and future vision-model calls can reuse the same frame-grid/transcript alignment.
- The Web UI and Side Panel render transcript segments grouped under the corresponding `W001`/`W002` visual windows, keeping the frame grid, time range, and subtitle lines together for BiliNote-style review.
- Generated notes can be copied or exported as Markdown files with the task title as the filename.
- Deterministic fallback notes when no LLM key or ASR model is installed.

## Quick Start

For a first run on Windows, print the machine-specific checklist first:

```powershell
cd D:\Projects\learnnote-assistant
.\scripts\first-run-checklist.ps1
```

The checklist summarizes D-drive data paths, Python/ffmpeg/yt-dlp readiness, optional `faster-whisper` and visual API gaps, Chrome/Edge availability, the unpacked extension path, the backend URL, sample-site URL, and the product verification command. It also separates required blockers from optional capability warnings: if only `WARN` items remain, the base workflow can still run with subtitle/remote-ASR/local-note fallbacks. It does not start services or read browser cookies. To write a machine-specific first-run guide under `data\first-run-guide.md`:

```powershell
.\scripts\first-run-checklist.ps1 -WriteGuide
```

Use the product launcher first. It keeps runtime files under the D-drive project `data\` directory, runs the local doctor, prints the extension load path, sets the backend origin, and then starts FastAPI:

```powershell
cd D:\Projects\learnnote-assistant
.\start-learnnote.ps1
```

For first-run verification, start the backend and local regression sample site together:

```powershell
cd D:\Projects\learnnote-assistant
.\start-learnnote.ps1 -WithSamples
```

This prints the Side Panel backend URL plus sample pages for direct MP4, HLS manifest, blob iframe fallback, POST play API replay, a generic nested player API, and the Chaoxing-style diagnostic mock. The sample server is stopped when the launcher exits, and its logs stay under `data\logs` on the D-drive project path.

The fastest first-use path is a five-minute product loop:

1. `.\scripts\first-run-checklist.ps1`: confirm there are no `FAIL` items. `WARN` means optional quality is missing, not that the base workflow is blocked.
2. `.\start-learnnote.ps1 -WithSamples`: start FastAPI plus the local MP4/HLS/blob/API/learning-platform sample site. Runtime files and logs stay under `D:\Projects\learnnote-assistant\data`.
3. Load the unpacked extension from `D:\Projects\learnnote-assistant\extension`, then keep the Side Panel backend URL as `http://127.0.0.1:8765`.
4. Open `http://127.0.0.1:8777/mp4.html` or `http://127.0.0.1:8777/chaoxing-mock.html`, play the video for a few seconds, then click Side Panel `预检资源` or `总结当前视频`.
5. Expected first success: the Side Panel shows a normal learning flow, a task writes artifacts under `data\tasks\{task_id}`, and the result tabs show note, transcript, slices, frame grids, and diagnostics.
6. When changing downloader, extension, startup, or UI code, run `.\scripts\verify-product.ps1 -Browser edge`.
7. Before handoff, run `.\scripts\audit-product-acceptance.ps1 -Browser edge`; add `-LearningUrl "<logged-in-course-url>"` only when a real logged-in course page is available.
8. Run `.\scripts\audit-product-readiness.ps1` to see the product closure matrix. It reports code/local evidence as `pass` and keeps live-site checks as `manual` until real browser audit reports prove them.

Open the local web UI after startup:

```text
http://127.0.0.1:8765
```

## Windows Desktop Client

The primary product is the local Windows desktop client. It opens in its own WebView2 window, starts FastAPI on `127.0.0.1`, stores tasks under the D-drive project directory, and shuts down the backend it owns when the window closes:

```powershell
.\start-desktop.ps1
```

The first run installs `pywebview` into the D-drive virtual environment. Tagged releases build a portable `LearnNote-Windows-x64.zip`; extract it to D: and run `LearnNote.exe`. The browser extension remains the current-page handoff: it detects the playing page and sends accessible media evidence to the desktop backend without recording the tab.

## Public Website

`site/` is the no-login public LearnNote introduction and download website. It is deliberately static: it does not expose FastAPI, accept video uploads, read browser cookies, or receive model API keys.

Preview it locally:

```powershell
python -m http.server 8790 --bind 127.0.0.1 --directory site
```

Start a temporary public site with no login prompt:

```powershell
.\scripts\start-public-site.ps1 -Detach
.\scripts\stop-public-site.ps1
```

The `Public Website` GitHub Actions workflow deploys the same static directory to GitHub Pages. Its Windows download buttons point to the latest GitHub Release.

## Optional Personal Server Deployment

The complete processing application can still be deployed privately for one owner. Unlike the public introduction site, this surface includes FastAPI, yt-dlp, FFmpeg, faster-whisper, uploads, task history, and persistent artifacts, so public mode requires HTTP Basic authentication.

### Docker / VPS

Copy the deployment environment file and replace the password with at least 12 random characters:

```bash
cp .env.deploy.example .env.deploy
docker compose --env-file .env.deploy up --build -d
```

Open `http://localhost:8765`. Data, uploads, task history, screenshots, and model caches persist in the `learnnote-data` volume. The container runs as a non-root user and exposes an unauthenticated `/health` endpoint only; the website and task APIs require the configured username/password. For a domain, put the container behind an HTTPS reverse proxy and set `LEARNNOTE_PUBLIC_ORIGIN` to the final origin.

Images are published from `main` to `ghcr.io/hurry060215-tech/learnnote-assistant:latest`. Because the source repository is private, authenticate Docker to GHCR before pulling unless package visibility is changed explicitly.

### Temporary Protected Processing URL

On Windows, this starts a separate empty data workspace and an optional Cloudflare Quick Tunnel. The generated password is written under the ignored D-drive `data\config` directory and is never committed:

```powershell
.\scripts\start-public-preview.ps1 -Tunnel
# detached mode
.\scripts\start-public-preview.ps1 -Tunnel -Detach
.\scripts\stop-public-preview.ps1
```

This protected processing URL is for personal remote access, not the public LearnNote website. Keep current-page browser-cookie extraction on the local extension/backend path.

Load the browser extension:

1. Open `chrome://extensions` or `edge://extensions`.
2. Enable Developer Mode.
3. Click "Load unpacked".
4. Select `D:\Projects\learnnote-assistant\extension`.
5. Open a video page, click the extension icon, then use the Side Panel.

The launcher runs the same readiness check as `.\scripts\doctor.ps1`. `PASS` means the base local workflow can run. `WARN` marks optional capability gaps such as missing `faster-whisper` or no multimodal API key. `FAIL` gives the command or path to fix before starting the backend. To install the optional local ASR dependency during startup:

```powershell
cd D:\Projects\learnnote-assistant
.\start-learnnote.ps1 -InstallAsr
```

If port `8765` is occupied, start the backend on another local port and put the same address in the Side Panel backend settings:

```powershell
.\start-learnnote.ps1 -Port 8766
```

For automation or backend-only debugging, `start-backend.ps1` remains available:

```powershell
.\start-backend.ps1 -Port 8765
```

The extension only accepts local backend origins (`127.0.0.1` or `localhost`), and its manifest keeps localhost permissions host-wide so non-default ports continue to work. Each launcher run sets `LEARNNOTE_BACKEND_ORIGIN` to the selected local port for the current PowerShell session, replacing a stale value from an earlier run so generated frame-grid, media, and export links point at the running backend.

## Local Browser Regression Samples

Use these pages before testing real course sites. They exercise the same generic extraction routes without depending on any external login state.

Start the backend in one terminal:

```powershell
cd D:\Projects\learnnote-assistant
.\start-learnnote.ps1
```

Start the sample site in another terminal:

```powershell
cd D:\Projects\learnnote-assistant
.\scripts\serve-samples.ps1
```

Or run the product launcher with `-WithSamples` to start the backend and sample site together:

```powershell
cd D:\Projects\learnnote-assistant
.\start-learnnote.ps1 -WithSamples
```

Open:

```text
http://127.0.0.1:8777
```

The sample server writes generated media fixtures to `data\test-runs\samples` on the D-drive project path. It does not commit binary videos to the repository.

Recommended browser checks with the unpacked extension loaded:

- `MP4`: open `http://127.0.0.1:8777/mp4.html`, play the video, then use `预检资源` or `总结当前视频`. Expected route: direct `/media/sample.mp4`.
- `HLS`: open `http://127.0.0.1:8777/hls.html`. Chrome may not play native HLS, but the extension should detect `/hls/master.m3u8` from DOM and backend ffmpeg should merge it.
- `Blob iframe`: open `http://127.0.0.1:8777/blob-iframe.html`. Expected route: iframe/player context plus blob-source mapping; no tab recording.
- `POST play API`: open `http://127.0.0.1:8777/post-api.html`. Expected route: XHR/POST candidate with safe headers and bounded body, resolving `playUrl` or `sources` to the real media URL.
- `Generic API`: open `http://127.0.0.1:8777/generic-player.html`. Expected route: generic XHR/POST candidate with JSON body replay, resolving nested `streamUrl`, `manifestUrl`, `play_url`, or fallback source fields to real media.
- `学习通 mock`: open `http://127.0.0.1:8777/chaoxing-mock.html`. Expected route: outer course page plus iframe player, `ananas/status/play` POST body with `objectid`/`dtoken`, visible cookie, Referer/Origin/XHR evidence, then normal media preflight. This is only a local diagnostic mock; it does not fake progress, answer questions, or call private course-completion APIs.

Run the product verification gate after broad downloader, detector, Side Panel, or startup changes:

```powershell
cd D:\Projects\learnnote-assistant
.\scripts\verify-product.ps1
```

That script runs the local doctor, a backend/sample smoke, and a real Edge MV3 extension smoke. It auto-picks loopback ports, keeps runtime artifacts under the D-drive project `data\` tree, and validates MP4, HLS, POST play API, generic nested player API, blob iframe fallback, the local Chaoxing-style evidence chain, and an extension-started download-only task. Use Chrome explicitly when browser-specific behavior matters:

```powershell
.\scripts\verify-product.ps1 -Browser chrome
```

Before handoff, run the product acceptance gate. It stitches the important evidence together: local doctor, real Edge/Chrome extension sample smoke, yt-dlp real-site task probe, learning-platform mock gate, and the product readiness matrix. If you have a logged-in course page, pass it so the real learning-platform row is audited in the same run:

```powershell
cd D:\Projects\learnnote-assistant
.\scripts\audit-product-acceptance.ps1 -Browser edge
.\scripts\audit-product-acceptance.ps1 -Browser edge -LearningUrl "https://mooc1.chaoxing.com/..."
```

The acceptance report is written under `data\test-runs\product-acceptance\{timestamp}\summary.md`. Without `-LearningUrl`, the gate can reuse a completed real learning-platform direct task after converting it into a redacted audit with `scripts\audit-learning-task-evidence.py --require-ready`; if no such task exists, the row remains manual.

Run the product readiness audit when deciding whether the current build is actually ready to hand off:

```powershell
cd D:\Projects\learnnote-assistant
.\scripts\audit-product-readiness.ps1
```

This matrix maps the current objective to evidence: BiliNote-style Side Panel flow, non-recording direct extraction, local video upload, visual slice notes, learning-platform diagnostics, local regression samples, startup/onboarding, generic adapter direction, and live-site audit coverage. It deliberately does not count local mocks as real YouTube/Bilibili/Chaoxing proof. To make those rows pass, create real reports with `.\scripts\audit-real-site.ps1 ... -Preflight -RequireReady` and, for learning platforms, `-RequireLearningProfile`.

Run the narrower local backend/sample smoke gate when changing downloader or detector contracts and you want faster failure isolation:

```powershell
cd D:\Projects\learnnote-assistant
.\scripts\e2e-local-smoke.ps1 -BackendPort 8790 -SamplesPort 8791
```

That script starts a temporary backend and sample server, then verifies MP4 preflight, HLS preflight, POST play API preflight, a real download-only task that writes `media.mp4`, and iframe/page fallback preflight. Add `-OpenBrowser` to also launch Chrome/Edge with a temporary profile and the unpacked extension opened on the sample site:

```powershell
.\scripts\e2e-local-smoke.ps1 -OpenBrowser
```

Run the real extension smoke when changing browser collection, `webRequest`, iframe fallback, or Side Panel start contracts:

```powershell
cd D:\Projects\learnnote-assistant
.\scripts\e2e-extension-smoke.ps1
```

That script launches a temporary Edge profile with the unpacked extension, starts the backend and sample server, then verifies the real MV3 service worker plus content/background collection for MP4, an extension-started `download_only` task that writes `media.mp4`, HLS, POST play API request body replay, generic nested player API replay, blob iframe page-scan fallback, and the local 学习通-style mock (`ananas/playurl/objectid/dtoken/iframe/cookie`). Use Chrome explicitly when needed:

```powershell
.\scripts\e2e-extension-smoke.ps1 -Browser chrome
```

For real sites, use the same evidence model instead of a site-specific assumption:

- A direct media URL, HLS/DASH manifest, or yt-dlp supported page is enough.
- If the page uses a player API, the Side Panel diagnostics should show `播放 API`, `POST/body`, `Referer`, `Origin`, `XHR`, `iframe`, Cookie count, and preflight status when those signals are available.
- If the page only exposes DRM/EME, unrecoverable `blob:`, or `MediaStream/srcObject`, the app should fail clearly and point to local upload instead of recording the tab.

Use the real-site audit script when checking YouTube/B站/学习通 or any other live site. It launches Chrome/Edge with the unpacked extension, starts the local backend, collects the same browser evidence as the Side Panel, optionally runs cookie-aware backend preflight, and writes redacted `audit.md` / `audit.json` reports under `data\test-runs\site-audits`:

```powershell
cd D:\Projects\learnnote-assistant
.\scripts\audit-real-site.ps1 "https://example.com/video-page" -Preflight
```

Use gate mode when you want the command itself to fail unless the page is actually ready for direct extraction:

```powershell
.\scripts\audit-real-site.ps1 "https://example.com/video-page" -Preflight -RequireReady
```

For yt-dlp-supported pages such as YouTube, Bilibili, or a generic extractor page, use a real download-only task probe plus a metadata-only yt-dlp probe instead of only resource preflight. This proves that the page is yt-dlp-resolvable and that the current-page workflow can save `media.mp4` locally:

```powershell
.\scripts\audit-real-site.ps1 "https://samplelib.com/sample-mp4.html" -TaskProbe -YtdlpProbe -RequireReady -TaskTimeout 180
```

To verify the backend page fallback without using captured browser media resources, add `-TaskProbePageOnly`. This is useful when you want to test page scanning / yt-dlp fallback separately from the extension's resource ranking:

```powershell
.\scripts\audit-real-site.ps1 "https://example.com/video-page" -TaskProbe -TaskProbePageOnly -YtdlpProbe -RequireReady -TaskTimeout 180
```

For logged-in course pages, use the learning-platform wrapper. It keeps the browser profile under the D-drive project data directory, pauses for login/playback, runs cookie-aware preflight, and requires the learning signal checklist by default:

```powershell
cd D:\Projects\learnnote-assistant
.\scripts\audit-learning-platform.ps1 "https://mooc1.chaoxing.com/..." -KeepBrowser
```

Rehearse the same gate against the local Chaoxing-style mock without using a real account:

```powershell
.\scripts\audit-learning-platform.ps1 -Mock
```

When the browser opens for a real site, log in if needed, play the target video for a few seconds, then return to the terminal and press Enter. The report starts with `Readiness`, `Failure reason`, and `Next step`, then expands the generic chain: browser playback evidence, auth/cookie context, replayable API body or direct media URL, and download preflight. For learning-platform pages it also lists `ananas`, `playurl/play_url`, `objectid`, `dtoken`, `iframe`, and `cookie` as a checklist instead of hiding them in raw logs. The wrapper enables `-RequireLearningProfile`; tune it with `-LearningRequiredSignals "ananas,playurl,iframe,cookie"` if a site does not use Chaoxing-style `objectid`/`dtoken`. Reports keep only evidence summaries: Cookie/Authorization values are not written, POST body content is replaced with field names and evidence flags, and URL query values are redacted.

## Local Storage On D

On this machine the project lives at `D:\Projects\learnnote-assistant`. The startup script creates a project-local virtual environment at `.venv` and keeps runtime outputs under the project `data\` directory. Set `LEARNNOTE_VENV_DIR` first if you want a different D-drive venv path:

- `data\uploads` for local uploads.
- `data\tasks` for task artifacts and generated notes.
- `data\model-cache` for Hugging Face / faster-whisper model cache.
- `data\pip-cache` for pip downloads.
- `data\temp` for backend process temporary files.
- `data\test-runs` for generated local test videos.
- `data\browser-profiles` for optional real-site audit browser profiles.
- `data\test-runs\site-audits` for redacted real-site and local browser audit reports used by `audit-product-readiness.ps1`.

To install the optional local ASR dependency into the D-drive project venv:

```powershell
cd D:\Projects\learnnote-assistant
.\start-learnnote.ps1 -InstallAsr
.\scripts\doctor.ps1
```

You can override the Python used to create the venv without changing where project dependencies and task data are stored:

```powershell
$env:LEARNNOTE_BOOTSTRAP_PYTHON="D:\Python312\python.exe"
.\start-learnnote.ps1
```

## Optional Model Settings

Transcription defaults to local `faster-whisper` with the `small` model, and can be switched per task to an OpenAI-compatible/Groq ASR endpoint. If ASR fails, LearnNote retains the downloaded media and diagnostic artifacts but marks the task failed instead of treating an error message as course content.

Windows defaults to CPU/int8 for reliability:

```powershell
$env:LEARNNOTE_WHISPER_DEVICE="cpu"
$env:LEARNNOTE_WHISPER_COMPUTE_TYPE="int8"
```

If your CUDA runtime is correctly installed, you can opt into GPU manually:

```powershell
$env:LEARNNOTE_WHISPER_DEVICE="cuda"
$env:LEARNNOTE_WHISPER_COMPUTE_TYPE="float16"
```

For OpenAI-compatible multimodal summary, set:

```powershell
$env:LEARNNOTE_LLM_API_KEY="..."
$env:LEARNNOTE_LLM_BASE_URL="https://api.openai.com/v1"
$env:LEARNNOTE_LLM_MODEL="gpt-4.1-mini"
```

The same Base URL and API Key fields are reused when the task's transcriber is set to `OpenAI-compatible ASR` or `Groq ASR`. For OpenAI use `whisper-1`; for Groq-style endpoints choose `whisper-large-v3` or the model name supported by that endpoint.

The Web UI and Side Panel include built-in OpenAI-compatible presets. Presets only fill the Base URL and model defaults; keys entered in either UI remain task-scoped, and providers without an ASR capability keep local `faster-whisper` transcription.

| Provider | Default model | Summary input |
| --- | --- | --- |
| DeepSeek | `deepseek-v4-flash` | Transcript/text |
| 通义千问 Qwen | `qwen-vl-max` | Transcript + frame grids |
| Kimi 月之暗面 | `kimi-k2.6` | Transcript + frame grids |
| 智谱 GLM | `glm-5v-turbo` | Transcript + frame grids |
| 豆包 火山方舟 | `doubao-seed-2-0-lite-260215` | Transcript/text |
| MiniMax | `MiniMax-M2.7` | Transcript/text |
| 百度千帆 ERNIE | `ernie-4.5-8k-preview` | Transcript + frame grids |
| OpenAI / Groq / Gemini | Provider preset | Capabilities shown in the UI |

Every model field remains editable. This is important for providers such as Volcengine Ark that may require a console-created endpoint or a region-specific model ID.

For a reusable local-only configuration, create `data/config/model-profiles/<name>.env` with
`LEARNNOTE_LLM_BASE_URL`, `LEARNNOTE_LLM_API_KEY`, and `LEARNNOTE_LLM_MODEL`, then start with
`./start-learnnote.ps1 -ModelProfile <name>`. The entire `data/config/` directory is ignored by Git,
and the launcher reports only the profile name. DeepSeek's official API is OpenAI-compatible and can
be used for transcript/text summarization, but its current models are text-only; use a vision-capable
provider when frame-grid image understanding is required.

For example, a profile named `ln` is started with:

```powershell
.\start-learnnote.ps1 -ModelProfile ln
```

Without a model key, the backend generates a deterministic local Markdown note from transcript segments and frame-grid indexes.

## Development Checks

```powershell
cd D:\Projects\learnnote-assistant
.\scripts\audit-stage.ps1
```

The stage audit checks working-tree changes, or the last commit when the tree is clean, and runs the narrow Node/Python checks that match the touched files. Use the full suite when changing broad contracts:

```powershell
.venv\Scripts\python.exe -m compileall backend\app
$env:PYTHONPATH="backend"
.venv\Scripts\python.exe -m unittest discover backend\tests
node --check extension\background.js
node --check extension\content.js
node --check extension\sidepanel.js
node --check web\app.js
```

Before calling the product complete, run:

```powershell
.\scripts\audit-product-readiness.ps1
```

Use `-RequireRealSiteAudits` when you want the command to fail until public MP4/HLS, yt-dlp-supported, and logged-in learning-platform audit rows have real non-local evidence.

## Boundaries

- `blob:` URLs without an underlying `.m3u8`, `.mpd`, video file request, or recoverable fetch/XHR Blob/ArrayBuffer/ReadableStream/MediaSource source mapping are reported as `drm_or_encrypted`.
- Fragment URLs such as isolated `.m4s` or `.ts` segments are not downloaded by themselves; they are used only to infer or preflight a real HLS/DASH manifest.
- The Learning Tong / Chaoxing first pass is deliberately lightweight: it relies on media URLs exposed to the browser and cookies from your active session.
- If a course page uses DRM/EME or never exposes a media manifest/video URL to the browser, the app reports a failure and asks you to use the local upload path.
