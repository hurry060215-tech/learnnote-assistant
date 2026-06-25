# LearnNote Assistant

BiliNote-style browser learning assistant for direct current-page video extraction, local video upload, transcription, frame-grid visual understanding, and Markdown note generation.

This project intentionally does **not** record the browser tab and does **not** bypass DRM, login, or course progress systems. It downloads media only when the current page exposes a normal accessible URL, HLS/DASH manifest, yt-dlp supported page, or a cookie-authorized resource visible to the active browser session.

## Features

- Chrome/Edge MV3 extension with a Side Panel.
- BiliNote-style workspace UI: source selection, processing options, task history, note/transcript/frame/diagnostic result tabs.
- BiliNote-style task stage rail for download, transcription, frame slicing, note generation, and completion.
- Markdown note export from both the local Web UI and the browser Side Panel.
- Current-page media detection from DOM, all-frame content scripts, Performance entries, and `webRequest`.
- Cookie handoff from the current browser session to the local backend at task start.
- Local FastAPI backend on `127.0.0.1:8765`.
- Download order: selected browser/media candidate first, then yt-dlp page resolver fallback.
- Download diagnostics: every task records the direct-file, manifest-ffmpeg, skipped blob/fragment, and yt-dlp attempts with status, HTTP code, content length, output file, and failure reason.
- Local video upload from both the Side Panel and the local web UI.
- Shared processing pipeline: normalize video, extract audio, transcribe, slice frames, build frame grids, summarize.
- Page subtitle tracks (`.vtt`, `.srt`, `.ass`, `.ssa`) are detected and preferred over Whisper when available.
- Structured failure codes: `no_media_found`, `auth_required`, `drm_or_encrypted`, `download_forbidden`, `unsupported_manifest`, `processing_failed`.

## What Works Now

- Direct current-page task creation from the extension Side Panel.
- DOM, iframe-aware content scripts, Performance, active `<video>` state, and `webRequest` resource discovery.
- Dynamic SPA video detection through MutationObserver, media event binding, periodic rescans, and PerformanceObserver resource updates.
- Cookie collection at task start for the page URL and detected media URLs.
- Main-video ranking based on the actively playing `<video>` first, then the largest visible video element.
- Candidate evidence from `webRequest`, including request type, HTTP status, MIME type, content length, initiator, and frame id when available.
- Playback-aware candidate ranking: the Side Panel boosts exact current `<video>` sources, same-frame media requests, and recent requests from blob-backed players before starting a task.
- Subtitle discovery from `<track>` elements, Performance entries, and `webRequest`.
- Direct video download for exposed MP4/WebM/MOV/MKV URLs.
- HLS/DASH manifest download through ffmpeg when a manifest URL is visible.
- yt-dlp page URL fallback for supported websites when direct browser resources are not usable.
- Local video upload from the extension and the local web UI.
- Shared video processing: normalize video, extract audio, transcribe with `faster-whisper` when available, extract frames, generate frame grids, and emit Markdown notes.
- Transcript priority: page subtitle track first, then local `faster-whisper` fallback.
- Configurable slicing: frame interval, grid layout, ASR model, and note style.
- Web UI and Side Panel diagnostic tabs show the selected resource, browser evidence, and every backend download attempt.
- Blob and media-fragment requests are kept as diagnostic clues instead of being hidden, but they are not treated as independently downloadable video files.
- Task records retain the frame interval, grid layout, ASR model, note style, and visual-understanding setting used for that run.
- Multimodal prompts are organized by frame-grid windows, pairing each visual slice with the transcript segment from the same time range.
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

Transcription defaults to `faster-whisper` with the `small` model. If `faster-whisper` is not installed or the model cannot load, the task still completes with a clear transcript warning and visual/text note fallback.

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

- `blob:` URLs without an underlying `.m3u8`, `.mpd`, or video file request are reported as `drm_or_encrypted`.
- Fragment URLs such as isolated `.m4s` or `.ts` segments are not downloaded unless a manifest is also detected.
- The Learning Tong / Chaoxing first pass is deliberately lightweight: it relies on media URLs exposed to the browser and cookies from your active session.
- If a course page uses DRM/EME or never exposes a media manifest/video URL to the browser, the app reports a failure and asks you to use the local upload path.
