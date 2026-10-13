# Whole-note personal review lifecycle

Related issue: [#151](https://github.com/hurry060215-tech/learnnote-assistant/issues/151).
This bounded addition does not complete progressive per-section factual validation.

The default reader exposes an explicit local action, **本人已核对**, with scope
**当前整篇笔记 · 本机个人核对**. Opening a note, generating a summary, an assistant
tool call, an export or a backup restore cannot activate this record. It is not
authenticated identity, another person's endorsement, or an AI truth judgment.
Existing uncertainty and source-location warnings remain visible and exportable.

## Version and concurrency contract

- Exact `kind/source_id` keys do not inherit annotation task-family migration.
- Current note content, the edition write generation and bounded local source
  witnesses determine freshness. Editing and returning to the same text remains
  stale. Source replacement, changed captions, page text or grid bytes invalidate
  the old record. Queued/running tasks cannot be marked.
- Missing/unreadable sources are disclosed as personal reading-only scope. A
  corrupt or unsafe current note is not markable. Revocation remains possible
  when current source data cannot be read; it does not modify source files.
- Required context/review revisions reject stale writes with HTTP 409. Request
  receipts allow an exact retry without reviving a later revoked state. Conflicts
  require refresh and a new explicit action.
- The API derives status on reads and after writes. It never sets claim
  `verification`, clears `review_required`, or promotes generated evidence quality.
- Original videos are not re-downloaded/scanned by this feature. A personal record
  does not establish video coverage or model-generated summary quality.

## Backup and data preservation

Learning-backup v2 includes strict bounded personal-review records; v1 remains
readable. Future versions, malformed JSON and incompatible destination records
fail before any restore writes. Review files share the existing personal-data
transaction, full destination preflight and reversible restore journal.

Restore imports only missing records. Existing local records, including revoked
ones, win. Imported marks remain **待本人重新核对** even if hashes match: a backup
cannot identify its author as the present operator. A missing edition restored
from either backup version receives a fresh local write ID; a backed-up assistant
write ID is never replayed. Existing local editions retain their original bytes.
Original source/note bytes
are not rewritten to embed a badge.

## Reproducible checks

`backend/tests/test_personal_reviews.py` uses temporary synthetic task artifacts
and material imports with real local HTTP and disk. It covers mark/revoke,
concurrent tabs, idempotent replay, edition/source changes, task families,
unavailable/corrupt/symlinked/oversized artifacts, backup compatibility, imported
records, local revocations, strict validation, failed writes and restore locks.
Existing learning-backup completeness and restore safety suites remain required.

`web/tests/personal_review.test.mjs` covers the controller's display and async
boundaries. `scripts/personal-review-acceptance.cjs` requires actual Microsoft
Edge and an isolated backend with external requests blocked. It records real
mark/edit/stale/revoke/restore/conflict/navigation operations and screenshots at
1440/390 pixels in light/dark themes. Passing synthetic checks does not establish
real model accuracy, a user's original-video quality or authenticated identity.
