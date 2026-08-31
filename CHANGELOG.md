# Changelog

All notable changes to LearnNote are documented here. The project follows semantic versioning while the `0.x` series is under active development.

## Unreleased

### Added

- Subtitle-ready progressive drafts, reconnectable SSE progress, per-attempt timing, batched frame extraction, bounded visual concurrency, and task-local visual caches.
- Canonical Unicode decoding and mojibake quarantine for UTF-8, UTF-16, GB18030, Shift-JIS and common legacy text paths.
- Evidence-first note documents, editable Word and print-ready PDF export, first-class local materials, a local study dashboard, and an opt-in community-perspective lane.
- A restrained glass-assisted desktop/mobile design system with five labelled mobile destinations, accessible 200% scaling, dark-mode fallbacks, and a simplified first-run path.

### Security

- The private data directory is no longer exposed as static web content; task assets use bounded allowlist routes.
- DOCX, PDF and Notion exports now share secret and signed-URL sanitization.
- Task and material deletion cascade through local evidence, community context and derived review records; index restore performs a white-listed migration with rollback snapshots.
- Study-card creation accepts only canonical local evidence and initializes FSRS state on the server.

## 0.1.55 - 2026-08-23

### Added

- Subtitle-first local study workflow, dynamic bilingual status copy, and evidence-grounded local task outputs are now included in the verified release.

### Fixed

- The browser extension no longer installs invasive page-world hooks for fetch, streams, MediaSource, WebSocket, and player libraries on every page and iframe.
- Media request capture is limited to media and XHR traffic; DOM and Performance collection now uses narrow selectors and incremental resource caching without a periodic fallback scan.
- Late extension recovery injects only the isolated lightweight content collector, preventing video playback and complex pages from stalling after detection starts.
- Page collection is now fully on demand: no script runs inside normal pages until the LearnNote Side Panel is opened, snapshots leave no observers or timers behind, and per-tab network capture expires after five minutes.

## 0.1.53 - 2026-08-06

### Added

- An Obsidian companion plugin can import and resync completed LearnNote tasks, preserve personal additions, and continue evidence-grounded course Q&A from the Obsidian sidebar.
- The desktop client now shows concise release notes after the first launch of an updated version and keeps the current version notes available from Settings.
- Release packaging checks now require an in-app release-note entry matching the client version.

### Fixed

- Release-tree and installed-client smoke tests now fail when bundled release notes are missing, incomplete, or version-mismatched.
- The Obsidian plugin workflow now pins third-party Actions to reviewed commit SHAs, restoring the repository reliability gate.

## 0.1.52 - 2026-08-01

### Fixed

- Media requests from nested course players now retain the iframe's actual Referer, so Chaoxing-style POST playback APIs keep the correct lesson context during extension handoff.
- Visual acceptance now follows the currently visible workspace state and accepts responsive task rows with restored actions instead of stalling on historical tasks or enforcing the obsolete fixed row height.

## 0.1.51 - 2026-07-30

### Fixed

- Result export and advanced-tool popovers now close after selection, on outside clicks, and with Escape instead of remaining over the note.

## 0.1.50 - 2026-07-28

### Fixed

- Republishes the verified 0.1.49 fixes under a new immutable release after the original release page could not accept its already-built assets.

## 0.1.49 - 2026-07-28

### Fixed

- The notes workspace now provides persistent controls for collapsing the navigation rail and notes list, plus a focus-reading mode that hides both panes.
- The advanced actions menu now uses grouped, labeled commands and no longer overflows or stretches the page with hidden task metadata.
- Broad AI assistant summary questions now use transcript windows across the full timeline, while legacy browser recommendations and player-page text are removed from assistant evidence.
- Bilibili transformed-cover detection now uses bounded string parsing instead of an expensive user-controlled regular expression.

## 0.1.48 - 2026-07-28

### Fixed

- New notes no longer embed raw browser-page recommendations, ads, player controls, or comments in the learning context, and existing notes hide the legacy noisy block when displayed.
- The desktop note outline now remains visible and clickable on the right while the document scrolls.

## 0.1.47 - 2026-07-28

### Fixed

- Local transcription now publishes an eight-second heartbeat and processed-audio progress instead of appearing frozen at 52% during long CPU transcriptions.
- LearnNote now keeps Hugging Face, XDG, and Torch model caches inside its configured data directory even when another desktop application defines machine-wide cache variables.

## 0.1.46 - 2026-07-28

### Fixed

- Bilibili DASH video and audio fragments are classified and paired before handoff instead of remaining unconfirmed fragments.
- Playing media can confirm audio from live `captureStream()` tracks and decoded-audio bytes even when the extension attaches after playback has started.
- AVIF and transformed image covers are excluded from media candidates instead of being mistaken for AVI video.
- Weak static media hints can no longer outrank verified same-frame playback resources.

## 0.1.45 - 2026-07-28

### Changed

- Browser captions only replace audio transcription when their timeline coverage is credible; comments, danmaku bursts, and partial visible captions remain fallback evidence.
- Appearance settings now apply consistently across the client with working light/dark themes, four palettes, three text sizes, three density levels, and a live preview.

### Fixed

- Bilibili `audio/mp4` M4S resources are classified as audio instead of generic fragments, while cover images, scripts, styles, and pseudo MIME URLs are excluded from media candidates.
- The settings page no longer overlaps the fixed navigation rail between 681 and 900 pixels.

## 0.1.44 - 2026-07-27

### Changed

- Bilibili and other yt-dlp-first platforms now resolve the page before direct browser media candidates so separate DASH audio and video streams are merged when possible.
- GitHub Actions use the reviewed setup-python 7.0.0, docker/metadata-action 6.2.0, and upload-artifact 7.0.1 releases.

### Fixed

- Provisional browser handoff evidence no longer reports an unconfirmed audio track as definitively missing or blocks note generation.
- Windows media probing explicitly decodes FFmpeg and FFprobe output as UTF-8, preventing complete videos with Chinese filenames from being misreported as missing all tracks and duration.
- Direct browser media candidates remain available when the preferred page resolver cannot acquire the media.
- Opening the browser fallback for a newly created task no longer makes the extension side panel discard the completed handoff when that client tab becomes active.

## 0.1.43 - 2026-07-26

### Changed

- GitHub Release publication now uses the runner's authenticated `gh` CLI, removing the final Node 20 action-runtime warning.
- Container and Pages workflows use the latest reviewed major releases of their pinned Actions; website visual tests use Playwright 1.62.

### Fixed

- Browser media detection no longer promotes Bilibili subtitle and caption endpoints to the primary video resource.
- Pending or confirmation-stage tasks can be abandoned and deleted immediately from the note library instead of becoming stuck in cancellation.
- yt-dlp TLS EOF failures use bounded retry with backoff and report a retryable network error instead of incorrectly claiming that the video server refused the request.
- Browser request context now forwards the real page user agent only when available and otherwise leaves yt-dlp request-header selection intact.

## 0.1.42 - 2026-07-25

### Changed

- GitHub Actions release, Pages, container, dependency-review, and checkout steps use their current Node 24-compatible major versions.
- Release workflows pin third-party Actions to reviewed commit SHAs while retaining their major-version comments for maintenance.
- Dependabot only raises Python and npm version requirements when the existing constraints do not already allow the update.
- Backend minimums now include the FastAPI, Uvicorn, multipart, Requests, and yt-dlp versions exercised by the final release gates.
- Container releases now publish immutable semantic-version tags alongside `latest` and commit-SHA tags.

### Fixed

- Release metadata, website links, browser-extension assets, and installer fallback version now stay aligned; issue templates no longer hard-code a stale example version.

## 0.1.41 - 2026-07-24

### Changed

- Browser handoff now reuses fresh media preflight results and opens the accepted task directly in the desktop client.
- Task polling is adaptive and updates live progress in place instead of rebuilding the task library and media reader.
- Desktop focus requests no longer reload the same task route, preserving video playback and reading position.
- The public container image is available anonymously from GHCR.

### Fixed

- Stable video identity no longer treats title updates, signed URL renewal, or resource-list changes as a different page.
- Retried extension handoffs are idempotent and cannot create duplicate tasks.
- Concurrent send clicks are collapsed into a single handoff request.
- Mobile note reading no longer places the fixed desktop library pane over the video and timeline.

## 0.1.40 - 2026-07-24

### Security

- Media preflight now validates DNS results, pins the checked destination, and revalidates every redirect before connecting.
- Provider detection requires exact host or subdomain boundaries instead of accepting lookalike hostnames.
- Task question fallback responses no longer expose exception details, local paths, or provider credentials.
- Replaced potentially expensive media URL and HLS key regular expressions with bounded linear parsers.
- Strengthened browser object URL validation and security regression tests.

## 0.1.39 - 2026-07-24

### Added

- Apache-2.0 open-source governance and third-party notices.
- Branded application, installer, website, and browser-extension assets.
- Browser-store listing, permission, privacy, and review documentation.
- CodeQL, dependency review, Dependabot, scheduled reliability checks, and protected-branch contribution flow.
- Previous-version upgrade, synthetic long-video, and model-provider contract gates.

### Changed

- Browser extension setup now distinguishes install, reload, and version update actions.
- Windows release signing covers the desktop executable as well as the installer when a certificate is configured.

## 0.1.38 - 2026-07-24

### Added

- Reproducible real teaching-video case on the public website.
- Privacy and security policies.
- Installed-release smoke testing and SHA-256 release checksums.

### Fixed

- Rejected or repaired notes containing unsupported duration, terminology, or example claims.
- Media-export integrity metadata now describes the exported media file.
- Temporary downloader cookie files are cleaned up after success or failure.
- Current Edge extension smoke tests use the current side-panel controls.
