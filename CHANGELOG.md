# Changelog

All notable changes to LearnNote are documented here. The project follows semantic versioning while the `0.x` series is under active development.

## 0.2.2 - Product workbench preview

- Restore a visible AI assistant with contextual conversation history, citations, suggestion prompts and saving answers to annotations.
- Restore six settings sections, model discovery/provider controls, transcription, style/template profiles, resource controls and reading preferences.
- Replace the sparse welcome page with source creation, processing presets, runtime status and recent notes; add consistent icons, outline navigation, focus reading and associated versions.
- Add extension style/format overrides, client preference loading and Markdown/SRT result saving while preserving on-demand capture.
- Fix the out-of-scope query reference after task creation and retain legacy model configuration on first use.

## 0.2.1 - Unified workspace preview

- Integrate courses, batch links, cited comparison, review proposals/plans, range learning, OCR, scoped questions, annotation editing and diagnostics into the new workspace.
- Export saved user revisions to Markdown, DOCX and PDF; optionally include personal annotations.
- Add storage inspection, explicitly scoped index backup/restore and cleanup preview.
- Exclude the legacy application shell and assets from desktop packages, enforced by the release-tree audit.
- Add a full browser acceptance flow for the unified tools and support short complete Chinese review facts.

## 0.2.0 - Redesign preview

- Replace the default application shell with an independent reading workspace: one creation dialog, source panel, editable user revisions, annotations and focused review.
- Preserve legacy specialist tools at `/web/classic.html` while moving core interactions off the old app script and layered stylesheets.
- Replace repetitive default fallback templates with explicitly labeled complete transcript extracts. Process long text-model inputs in blocks rather than silently truncating the tail.
- Redesign the public website and README around actual user workflows and stable release links.
- Add optimistic edit-conflict checks, full-source preservation tests and a browser interaction gate for the new workspace.

## 0.1.56 - 2026-09-06

### Added

- Manual courses with ordered sources, bounded public playlist previews, paused batch submission, course-scoped review and citation-based keyword comparison. Shared terms are explicitly not treated as causal or semantic agreement.
- Learning tasks for selected cached-video ranges with relative timeline labels and conservative subtitle reuse. Clip exports now transcode accurately instead of including an earlier keyframe interval.
- Optional local RapidOCR with bounded frame sampling, image-hash cache, bounding boxes, confidence and an unreviewed status; OCR-only frames are kept out of vision-model requests.
- A permanent browser interaction gate for complete document reading, code contrast, review-source access, progress updates and mobile title clearance.

- Durable, bounded local task execution with one heavy worker per data directory, immediate cancellation of queued work, and restart recovery that never persists browser cookies or model keys in the queue.
- Personal annotations stored independently of generated notes, preserved across note versions and same-file reimports, with optional DOCX/PDF exports containing personal additions.
- Complete local-source reading with progressive long-document loading, editable export tables, embedded local keyframes, and release SBOM/resolved-dependency evidence.

### Fixed

- Windows desktop builds include the local faster-whisper runtime and validate native ASR/OCR imports before packaging; model weights remain an on-demand download.

- Cancelled queue Futures no longer execute callbacks or stop subsequent work; stopped queues reject new jobs. Build/signing command failures now stop Windows release packaging.

- FSRS graduation no longer writes a null step into SQLite; new cards use native FSRS initialization, and existing schedules can be rebuilt explicitly from complete review histories after a backup. Study exports no longer inherit the 500-row UI pagination limit.

- Restoring the task index no longer replaces the database containing local materials and canonical evidence.
- Timestamps alone no longer imply verified claims; source matching uses numeric time ranges and preserves existing table-of-contents anchors.
- Code fences, comments, indentation and paragraphs survive normalization, import, reading and export. Long materials are no longer silently limited to 40 anchors or 4,000 characters per anchor.
- Study day boundaries and activity follow an IANA timezone, including DST; paused plans reject reviews and hide due-card actions.
- Review sessions display short extractive source points with visible evidence links, deduplication and live progress, rather than whole-note Markdown answers.
- Video upload limits and disk reserve checks apply before multipart spooling and during writes; failed uploads clean up partial files.
- Extension heartbeat expiry now accommodates the two-minute MV3 heartbeat and a delayed tick.
- Mobile reader headers no longer overlap the top bar; empty libraries have one primary action, model setup is directly discoverable, and code text remains readable in both themes.
- Reliability workflow braces, outdated visual assertions and masked native-command failures were corrected. Visual acceptance now runs on relevant pull requests.

### Release engineering

- GitHub Releases are assembled as resumable drafts, downloaded and checksum-verified before publication. Published assets are never clobbered by reruns.
- Release builds emit a CycloneDX inventory, resolved Python versions and source metadata, and request a pinned GitHub provenance attestation. Hosted signing/store/publication checks remain release-time validations.

### Earlier main-preview additions

- Subtitle-ready progressive drafts, reconnectable SSE progress, per-attempt timing, batched frame extraction, bounded visual concurrency, and task-local visual caches.
- Canonical Unicode decoding and mojibake quarantine for UTF-8, UTF-16, GB18030, Shift-JIS and common legacy text paths.
- Evidence-first note documents, editable Word and print-ready PDF export, first-class local materials, a local study dashboard, and an opt-in community-perspective lane.
- A restrained glass-assisted desktop/mobile design system with four purpose-led mobile destinations, accessible 200% scaling, dark-mode fallbacks, and a simplified first-run path.
- Guided model setup with provider presets, official Key-console shortcuts, model discovery, a real short-chat connection check, secure Windows credential storage, and automatic return to the interrupted learning flow.

### Security

- The private data directory is no longer exposed as static web content; task assets use bounded allowlist routes.
- DOCX, PDF and Notion exports now share secret and signed-URL sanitization.
- Task and material deletion cascade through local evidence, community context and derived review records; index restore performs a white-listed migration with rollback snapshots.
- Study-card creation accepts only canonical local evidence and initializes FSRS state on the server.
- Model connection checks accept only built-in HTTPS provider hosts or loopback endpoints, never persist the submitted Key, and use a fixed prompt without learning material.

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
