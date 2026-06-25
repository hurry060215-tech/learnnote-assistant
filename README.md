# LearnNote Assistant

BiliNote-style browser learning assistant for direct current-page video extraction, local video upload, transcription, frame-grid visual understanding, and Markdown note generation.

This project intentionally does **not** record the browser tab and does **not** bypass DRM, login, or course progress systems. It downloads media only when the current page exposes a normal accessible URL, HLS/DASH manifest, yt-dlp supported page, or a cookie-authorized resource visible to the active browser session.

## Features

- Chrome/Edge MV3 extension with a Side Panel.
- Current-page media detection from DOM, Performance entries, and `webRequest`.
- Cookie handoff from the current browser session to the local backend at task start.
- Local FastAPI backend on `127.0.0.1:8765`.
- Download order: yt-dlp page resolver, then direct MP4/WebM/MOV/MKV, then ffmpeg HLS/DASH.
- Local video upload from both the Side Panel and the local web UI.
- Shared processing pipeline: normalize video, extract audio, transcribe, extract frames, build frame grids, summarize.
- Structured failure codes: `no_media_found`, `auth_required`, `drm_or_encrypted`, `download_forbidden`, `unsupported_manifest`, `processing_failed`.

## What Works Now

- Direct current-page task creation from the extension Side Panel.
- DOM, Performance, and `webRequest` resource discovery.
- Cookie collection at task start for the page URL and detected media URLs.
- Direct video download for exposed MP4/WebM/MOV/MKV URLs.
- HLS/DASH manifest download through ffmpeg when a manifest URL is visible.
- yt-dlp page URL fallback for supported websites.
- Local video upload from the extension and the local web UI.
- Shared video processing: normalize video, extract audio, transcribe if `faster-whisper` is available, extract frames, generate 3x3 frame grids, and emit Markdown notes.
- Deterministic fallback notes when no LLM key or ASR model is installed.

## Quick Start

```powershell
cd learnnote-assistant
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

## Optional Model Settings

Transcription defaults to `faster-whisper` with the `small` model. If `faster-whisper` is not installed or the model cannot load, the task still completes with a clear transcript warning and visual/text note fallback.

For OpenAI-compatible multimodal summary, set:

```powershell
$env:LEARNNOTE_LLM_API_KEY="..."
$env:LEARNNOTE_LLM_BASE_URL="https://api.openai.com/v1"
$env:LEARNNOTE_LLM_MODEL="gpt-4.1-mini"
```

Without a model key, the backend generates a deterministic local Markdown note from transcript segments and frame-grid indexes.

## Development Checks

```powershell
cd learnnote-assistant
python -m compileall backend\app
python -m unittest discover backend\tests
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
