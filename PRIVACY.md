# LearnNote Privacy

LearnNote is designed as a local-first video learning assistant. This document
describes the data the current implementation handles and when that data can
leave the computer.

## Local backend and data directory

The installed Windows client starts a FastAPI service on `127.0.0.1` by
default. The desktop interface, browser extension, and processing pipeline use
that local service. No LearnNote account or project-operated cloud backend is
required for the normal desktop workflow.

Videos, uploads, downloaded media, subtitles, audio, frame images, visual
grids, notes, task metadata, model caches, update installers, exports, and the
embedded browser profile are stored under the configured LearnNote data
directory. The initial directory is based on the installation/runtime
location; the Windows client lets the user move it to another non-system drive.

Data is retained until the user deletes the relevant task, model/cache data, or
the data directory. Backups and copies made by the user are outside LearnNote's
control.

## API keys

When an API key is saved in the installed Windows client, LearnNote stores it
in Windows Credential Manager using a `LearnNote/model/<provider>` target. The
key is loaded into the local application process when required and is sent to
the selected model provider to authenticate the requested operation.

LearnNote does not intentionally write saved API keys into task JSON,
diagnostic reports, or export bundles. Source/development deployments that use
environment variables or custom scripts remain the operator's responsibility.

## Browser extension data

The Chrome/Edge extension observes the current tab's video elements, iframe
context, subtitles, and media-related network requests so it can build a local
candidate list. A recovery cache of up to 120 media candidates can be kept in
`chrome.storage.local` for up to 30 minutes and is cleared on tab close,
navigation, or a capture-context reset. The persisted cache excludes Cookie
and Authorization request headers, but can contain media URLs, page/iframe
URLs, Referer/Origin metadata, and a size-limited replayable request body.
That observation stays in the browser extension until a LearnNote action needs
the local backend.

When the user opens or reruns the side-panel preflight, selects a candidate, or
clicks **Send to LearnNote**, the extension can read and send the following to
the local backend:

- page URL, title, limited page text, iframe and active-player metadata;
- browser subtitle cues and media resource URLs;
- selected request/response headers and replay evidence needed to fetch media;
- cookies for the page and candidate media domains, including partitioned
  cookies when the browser exposes them.

Cookies are not sent to a LearnNote-operated cloud service. They are used by
the local downloader to access media that the current browser session can
already access. Persisted task snapshots and diagnostics redact cookie and
authorization values.

For compatibility with `yt-dlp`, LearnNote can create short-lived
`cookies.txt` or `subtitle_cookies.txt` files in the local task directory.
They are deleted in a `finally` cleanup after each media or subtitle download
attempt, including failed attempts. A process crash or forced termination can
still interrupt cleanup, so the task directory should be treated as sensitive.

## Network connections

LearnNote makes network requests only for selected features and normal media
access:

- **Video and subtitle retrieval:** the downloader contacts the page, media
  hosts, CDNs, and supported platform endpoints supplied by the user or
  detected by the extension.
- **Remote transcription:** when an OpenAI-compatible or Groq-style remote ASR
  engine is selected, the extracted audio is uploaded to the configured
  provider. Local `faster-whisper` transcription does not upload audio for
  transcription, although model files may need to be downloaded initially.
- **Text and vision models:** prompts, transcript excerpts, questions, and,
  when visual understanding is enabled, frame-grid images are sent to the
  configured model endpoint. Provider presets include third-party services;
  a custom OpenAI-compatible endpoint can also be configured.
- **Model/tool downloads:** local model files and downloader dependencies may
  be fetched from their upstream distribution services during setup or first
  use.
- **Updates:** the Windows client checks this repository's GitHub Releases
  endpoints. If the user downloads an update, it retrieves the installer and
  published checksum from GitHub and verifies SHA-256 before installation.

Each third-party service applies its own privacy, retention, account, and model
training terms. Users should select providers and settings appropriate for the
sensitivity of their course material.

## Telemetry and crash reports

The current repository does not include a product analytics, advertising,
behavioral tracking, or automatic crash-reporting integration. LearnNote does
not intentionally send task usage statistics to the project maintainer.

Operating systems, browsers, GitHub, video sites, model providers, package
registries, reverse proxies, and custom deployment infrastructure may maintain
their own network or access logs.

## Exports, diagnostics, and sharing

Exports and diagnostic reports are created locally. LearnNote redacts known
cookie, authorization, API-key, request-body, and sensitive query values from
persisted diagnostic surfaces, but users should still review files before
sharing them. Video titles, page domains, transcript text, notes, screenshots,
and timing information may remain because they are part of the learning task.

Do not attach unreviewed task directories or full export bundles to public
issues. Follow the reporting guidance in [SECURITY.md](SECURITY.md).

## Custom server deployments

Docker/server deployments are not equivalent to the default local desktop
boundary. The operator determines who can connect and is responsible for
authentication, HTTPS, storage encryption, retention, backups, logging, and
deletion. A remote deployment can receive every item that the browser extension
or web client submits to it.

## Questions and privacy issues

For a non-sensitive question, open a
[GitHub issue](https://github.com/hurry060215-tech/learnnote-assistant/issues/new).
Do not post credentials, private URLs, personal data, or unredacted diagnostics
publicly. For a possible vulnerability or data exposure, use the private
reporting process described in [SECURITY.md](SECURITY.md).
