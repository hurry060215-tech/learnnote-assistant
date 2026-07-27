# Changelog

All notable changes to LearnNote are documented here. The project follows semantic versioning while the `0.x` series is under active development.

## Unreleased

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
