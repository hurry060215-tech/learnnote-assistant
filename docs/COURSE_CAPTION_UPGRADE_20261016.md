# Course caption retry and explicit visual upgrade

## User-visible boundary

A failed caption-only episode offers **重试字幕总结**. The request is bound to
course revision, episode ID, task ID and task generation. Its options force text
mode, remote visual analysis off and local OCR off. It reuses the saved transcript
and does not download the source again.

An eligible caption-only source separately offers **补充画面笔记…**. Its review
uses the saved model route and frozen current processing options. It shows:

- Canonical download source URL and model address/name. The exact model-bound
  title/URL appear separately from the download source, using server-provided
  `model_source` metadata. Known credential patterns are masked; review is still
  required. The browser never reconstructs or guesses the sanitized values.
- Per-episode media/processing MB budget. This is checked against downloaded
  media size, not a hard transfer-byte cap; traffic may exceed it before rejection.
- Requested frame interval, frame-count ceiling and per-call grid batch ceiling;
  resource/model constraints may lower these. Multiple model batches may be sent.
- Caption text, source title/URL and extracted frames leave the local backend for
  the selected model. Gateway forwarding and unknown total charges are disclosed.

Download permission and model sharing have separate, initially unchecked boxes.
Both are required before submission. Model route or processing option changes,
Cancel, Close, Escape, Back and source navigation invalidate the review. No old
response can submit another course or replace a newer view. An already submitted
request is not revoked by closing its window; errors are never automatically retried.

The source episode remains bound to the original caption task and its original
artifacts. A successful upgrade is a linked child with its own open/progress action.
Existing active/media-backed children should be opened rather than downloaded again.

## Validation

- `node web/tests/course_episode_retry.test.mjs`: 8 identity/retry/lifecycle tests.
- `node web/tests/course_episodes.test.mjs`: 24 consent, route/options, disclosure,
  stale-response, cancel and duplicate-submission tests.
- All 80 `web/tests/*.test.mjs` files pass on this change.
- All 240 script tests pass (3 existing skips), including JavaScript architecture,
  release-tree and UI cache contracts; existing CSS
  tokens/components are reused with no stylesheet or CSS-budget increase.
- `scripts/course-upgrade-fixture.py` was exercised through FastAPI TestClient
  against backend `e49c89d`: real preview, linked-child admission, same-token replay,
  new-review rejection and caption-summary retry passed. Projection checks confirm
  that active-child admission hides the upgrade action, keeps the original task
  binding, and exposes the linked child and source generation. The exact sanitized
  `model_source` matches the backend helper, and child-owned reviewed captions match
  their persisted SHA-256 and source/episode identity. Only synthetic task data
  was used. Scheduler and model validation boundaries were patched; no processing,
  media download or model request executed.

Two browser gates are wired into the existing Windows UI workflow:

```
node scripts/course-upgrade-acceptance.cjs http://127.0.0.1:18940 build/course-upgrade-synthetic-ui
node scripts/course-upgrade-api-acceptance.cjs build/course-upgrade-ui
```

The first runs the production frontend against strict synthetic HTTP responses,
including delayed preview dismissal and repeated clicks. The second starts an
isolated real backend with synthetic saved captions and deferred processing,
exercises the real course routes, and captures 1280/1440/768/390 light/dark reviews
and consent controls. It verifies the original task manifest and transcript/note
bytes, linked-child navigation, paused-review rejection and original-course binding.

Actual browser screenshots are **pending hosted Windows/Edge execution**. Local
Chromium could not create its required socket in this executor, and the supported
escalation failed before browser startup. No screenshot or native WebView pass is
claimed from local unit/API tests. Inspect the resulting PNGs before visual approval.
