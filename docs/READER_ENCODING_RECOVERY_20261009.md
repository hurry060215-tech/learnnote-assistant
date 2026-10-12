# Stored-document encoding recovery (#150)

The default reader exposes **更多 → 重新选择原文编码** for imported TXT,
Markdown and HTML documents. It loads the current encoding, retains the local
original bytes, and asks for explicit confirmation before rebuilding the text
and evidence using the selected encoding. PDF continues to use the OCR path;
video tasks and their material projections do not expose this action.

The dialog explains that existing references need to be checked after a change.
Closing it does not undo an already submitted operation. Repeated submissions
are blocked, including reopening the same material while its request is pending.
Cancel, Escape, Back, newer tools and source navigation invalidate late UI
results. A response cannot reopen the dialog or select a different source.

The re-decode endpoint accepts an optional `expected_updated_at` field. A stale
reader receives HTTP 409 before rewriting anything. The transaction's existing
concurrent-write check also remains active. Existing callers that send only
`encoding` remain supported. Missing originals, invalid decoding, integrity
failure and SQLite failure return actionable errors without replacing evidence.

Verification is split deliberately:

- `backend/tests/test_material_redecode*.py` exercises real local storage/API
  recovery, original bytes, card references, stale versions and rollback.
- `web/tests/desk_material_encoding.test.mjs` executes the controller with
  controlled request ordering, failures and navigation events.
- `scripts/study-product-visual-acceptance.cjs` calls
  `reader-encoding-acceptance.cjs` in the existing Windows/Edge CI job. It clicks
  the actual reader controls, checks raw downloads and evidence IDs, rejects an
  invalid encoding and a stale version, and holds a real response across Escape
  and selection of another source. It captures `reader-encoding-recovered.png`.

Cloud verification uses synthetic local fixtures and the offline backend guard.
No cloud localhost browser run is part of that verification; actual browser
acceptance is supplied by the Windows/Edge job.
