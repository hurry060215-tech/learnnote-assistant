# LearnNote Assistant

BiliNote-style browser learning assistant for direct current-page video extraction, local video upload, transcription, frame-grid visual understanding, and Markdown note generation.

This project intentionally does **not** record the browser tab and does **not** bypass DRM, login, or course progress systems. It downloads media only when the current page exposes a normal accessible URL, HLS/DASH manifest, yt-dlp supported page, or a cookie-authorized resource visible to the active browser session.

## Features

- Chrome/Edge MV3 extension with a Side Panel.
- BiliNote-style workspace UI: source selection, processing options, task history, note/transcript/frame/diagnostic result tabs.
- Richer BiliNote-style reading workspace with task search/filter, status counters, Markdown rendering, frame-grid preview, and failure recovery hints.
- BiliNote-style task stage rail for download, transcription, frame slicing, note generation, and completion.
- Transcript timeline view aligns each subtitle segment with its frame-grid visual window, so notes can be reviewed by time slice instead of as a flat transcript.
- Markdown note export from both the local Web UI and the browser Side Panel.
- Study bundle export from both UIs: Markdown note, task metadata, transcript JSON, visual-window index, frame-grid screenshots, and a redacted machine-readable `manifest.json` in one zip.
- Standalone manifest export from both UIs for the current task route, audit gates, media evidence, transcript/visual-window counts, and artifact list.
- Current-page media detection from DOM, all-frame content scripts, Performance entries, and `webRequest`.
- `webRequest` captures media candidates as soon as response headers arrive, so long-running video/range streams do not have to finish before they can be selected.
- Main-world fetch/XHR hook for media URLs exposed in text, JSON, playlist, or script responses before they appear in `<video>`.
- JSON/HTML script media-field discovery for extensionless player APIs such as `hls`, `dashUrl`, `playUrl`, or `videoUrl` when sibling metadata or field names identify HLS/DASH/video content.
- URL-encoded and base64-wrapped media field values are decoded during page scanning and main-world response inspection.
- Blob/MSE-backed player recovery: when a page fetches an accessible media response as a `Blob`, `ArrayBuffer`, or `ReadableStream` chunk, constructs a `Blob`, or appends the buffer to a `MediaSource`/`SourceBuffer`, the extension maps that generated `blob:` playback URL back to the original mp4/FLV/HLS/DASH request and ranks it as the current video candidate.
- Backend page scanner for manually pasted page URLs, so the local Web UI can try direct media extraction before yt-dlp fallback.
- Manual URL tasks can explicitly force a pasted extensionless link to be treated as a video file, HLS manifest, or DASH manifest instead of only relying on suffix detection.
- Manual URL tasks in the Web UI can preflight direct media links before task creation and can run download-only mode to save an exportable local `media.mp4` without transcription or summarization.
- Iframe/player-page fallback: when the top course page is only a shell, the backend also tries the active frame URL, candidate page URL, Referer, and initiator as page-scan and yt-dlp fallback targets.
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

- Direct current-page task creation from the extension Side Panel.
- DOM, iframe-aware content scripts, Performance, active `<video>` state, and `webRequest` resource discovery.
- Page-network hook discovery for mp4/FLV/HLS/DASH/subtitle URLs embedded in fetch/XHR text responses. The hook also records Blob object URL, fetch stream chunk, and MediaSource source mappings when the page builds playback from accessible media responses; it does not record playback or inspect binary video payloads.
- Page-global player config discovery: the page hook scans bounded common globals such as `__playInfo`, `playerConfig`, `videoInfo`, and matching video/player/media keys for mp4/FLV/HLS/DASH/subtitle URLs, including encoded fields, without recording playback.
- Extensionless manifest-body discovery: if a player endpoint such as `/api/play?lesson=...` returns an HLS/DASH manifest body with a generic MIME like `application/octet-stream`, the page hook promotes the response URL itself to a direct HLS/DASH candidate.
- Backend page-text scanning for manually submitted URLs: HTML/JSON/script responses are scanned for absolute or relative mp4/FLV/HLS/DASH/subtitle URLs before yt-dlp is tried.
- Extensionless API URL scanning: JSON fields or inline script fields like `hls`, `dashUrl`, `playUrl`, and `videoUrl` can become candidates even when the URL is `/stream?lesson=...` instead of ending in `.m3u8`, `.mpd`, `.flv`, or `.mp4`.
- Extensionless browser media request capture: if Chrome reports a `webRequest` as `media`, the extension keeps it as a direct video candidate even when the URL is `/play?id=...` and the server only returns a generic MIME type.
- Frame-aware context aggregation: the extension asks every reachable frame for page text, active video state, and media resources before ranking candidates.
- Frame-aware fallback download: if the outer page cannot be resolved, backend page scanning and yt-dlp fallback are retried against the detected player iframe, candidate page URL, Referer, and request initiator.
- Dynamic SPA video detection through MutationObserver, media event binding, periodic rescans, and PerformanceObserver resource updates.
- Cookie collection at task start for the page URL and detected media URLs.
- Browser-context download replay: direct media, subtitles, ffmpeg HLS/DASH merges, and yt-dlp page fallback reuse safe request headers plus the task-start cookie jar where applicable. Captured `Cookie` and `Authorization` headers are never replayed from request metadata; cookies are synced only through the explicit task/preflight handoff.
- POST playback API replay: when the browser reaches a `/play`/`stream` JSON endpoint through a text or form POST, the extension can hand its bounded request body to the backend so preflight/download resolves the embedded mp4/FLV/m3u8/mpd URL instead of retrying the endpoint as a plain GET.
- Browser-context preflight: selected mp4/FLV/HLS/DASH candidates can be checked with a small local backend probe before the full download. The result reports strategy, HTTP status, MIME type, content length, bytes checked, safe request-header names, and structured failure codes.
- Side Panel task start now preflights ranked direct-download candidates in order and automatically switches to the first reachable mp4/FLV/HLS/DASH resource, so a stale or forbidden top candidate does not stop the workflow when another visible media URL works.
- Side Panel also has a download-only current-page action: it uses the same preflight, cookie handoff, direct downloader, manifest merge, and yt-dlp fallback, then saves an exportable local `media.mp4` without transcription, slicing, or summarization.
- Main-video ranking based on the actively playing `<video>` first, then the largest visible video element.
- Candidate evidence from `webRequest`, including request type, HTTP status, MIME type, content length, initiator, and frame id when available.
- Long-running media responses are added from `onHeadersReceived`, then merged again on completion if the request later finishes.
- Playback-aware candidate ranking: the Side Panel boosts exact current `<video>` sources, same-frame media requests, recoverable Blob/ArrayBuffer/ReadableStream/MediaSource source mappings, and recent requests from Blob/MSE-backed players before starting a task.
- DRM-aware failure boundary: if a page triggers EME/DRM signals and exposes no downloadable mp4/FLV/HLS/DASH candidate, the task fails early as `drm_or_encrypted` and keeps the key-system/init-data evidence in diagnostics.
- Recoverable fragment URLs such as `.../master.m3u8/segment.ts` or `.../manifest.mpd/chunk.m4s` are promoted to inferred manifest candidates.
- Subtitle discovery from `<track>` elements, Performance entries, and `webRequest`.
- Direct video download for exposed MP4/FLV/WebM/MOV/MKV URLs.
- HLS/DASH manifest download through ffmpeg when a manifest URL is visible.
- yt-dlp page URL fallback for supported websites when direct browser resources are not usable.
- Local video upload from the extension and the local web UI.
- Shared video processing: remux/standardize local and downloaded videos to `media.mp4`, extract audio, transcribe with local `faster-whisper` or OpenAI-compatible/Groq ASR when selected, extract frames, generate frame grids, and emit Markdown notes.
- Transcript priority: browser/player subtitle cues first, page or yt-dlp platform subtitle second, embedded text subtitle third, then selected ASR engine fallback.
- Configurable slicing: frame interval, grid layout, ASR model, and note style.
- Web UI and Side Panel diagnostic tabs show the selected resource, browser evidence, and every backend download attempt.
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

```powershell
cd D:\Projects\learnnote-assistant
.\start-backend.ps1
```

Open the local web UI:

```text
http://127.0.0.1:8765
```

Load the browser extension:

1. Open `chrome://extensions` or `edge://extensions`.
2. Enable Developer Mode.
3. Click "Load unpacked".
4. Select `learnnote-assistant/extension`.
5. Open a video page, click the extension icon, then use the Side Panel.

## Local Storage On D

On this machine the project lives at `D:\Projects\learnnote-assistant`. The startup script creates a project-local virtual environment at `backend\.venv` and keeps runtime outputs under the project `data\` directory:

- `data\uploads` for local uploads.
- `data\tasks` for task artifacts and generated notes.
- `data\model-cache` for Hugging Face / faster-whisper model cache.
- `data\pip-cache` for pip downloads.
- `data\temp` for backend process temporary files.
- `data\test-runs` for generated local test videos.

To install the optional local ASR dependency into the D-drive project venv:

```powershell
cd D:\Projects\learnnote-assistant
.\start-backend.ps1 -InstallAsr
```

You can override the Python used to create the venv without changing where project dependencies and task data are stored:

```powershell
$env:LEARNNOTE_BOOTSTRAP_PYTHON="D:\Python312\python.exe"
.\start-backend.ps1
```

## Optional Model Settings

Transcription defaults to local `faster-whisper` with the `small` model, and can be switched per task to an OpenAI-compatible/Groq ASR endpoint. If local or remote ASR is unavailable, the task still completes with a clear transcript warning and visual/text note fallback.

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

Without a model key, the backend generates a deterministic local Markdown note from transcript segments and frame-grid indexes.

## Development Checks

```powershell
cd D:\Projects\learnnote-assistant
backend\.venv\Scripts\python.exe -m compileall backend\app
$env:PYTHONPATH="backend"
backend\.venv\Scripts\python.exe -m unittest discover backend\tests
node --check extension\background.js
node --check extension\content.js
node --check extension\sidepanel.js
node --check web\app.js
```

## Boundaries

- `blob:` URLs without an underlying `.m3u8`, `.mpd`, video file request, or recoverable fetch/XHR Blob/ArrayBuffer/ReadableStream/MediaSource source mapping are reported as `drm_or_encrypted`.
- Fragment URLs such as isolated `.m4s` or `.ts` segments are not downloaded unless a manifest is also detected.
- The Learning Tong / Chaoxing first pass is deliberately lightweight: it relies on media URLs exposed to the browser and cookies from your active session.
- If a course page uses DRM/EME or never exposes a media manifest/video URL to the browser, the app reports a failure and asks you to use the local upload path.
