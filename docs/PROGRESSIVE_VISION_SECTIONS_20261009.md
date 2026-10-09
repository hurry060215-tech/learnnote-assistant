# Completed vision-batch drafts during generation

Refs #151 and #148. Both epics remain open. This increment exposes actual
completed model output while later existing batches and the final merge run.
It does not call the earlier temporal transcript outline generated chapters.

## Reader behavior and trust boundary

After each successful non-streaming vision batch, the existing coordinator
writes the batch's completed text before dispatching another batch. Concurrent
batches can finish out of source order; their readable sections appear sorted
by source time. Cache hits take the same path. No extra model request, remote
verification, credentials, provider, or streaming requirement is introduced.
The existing unsupported-vision/text fallback remains available.

The desktop reader keeps the transcript excerpt draft and adds a clearly
separated generated-section area. Every generated section says **草稿 ·
证据补充中 · 未完成最终校验**. The canonical text/structure checks run first;
locally unsupported claims get the same conservative visible review markers
used by final publication. This preliminary projection cannot declare a
section or note verified. Final normalization, grounding, and claim handling
remain on the existing final publication path. Failed/corrupt merges leave
readable drafts without publishing `note.md`.

`draft.partial.md` is excluded from both library/assistant evidence indexing
and task-QA note citations, including after merge failure changes the summary
diagnostic source to `local-template`. Original transcript/source evidence
continues to work. An explicitly requested portable copy can include this
draft, retaining its draft and claim-review warnings; no final status is
asserted. The task artifact projection reports `partial_draft_available` and
never reports a partial artifact as final. The failure reader does not collapse
completed generated sections as if they were only transcript excerpts.

The reader skips unchanged editions and preserves its source-heading offset
when earlier batches arrive. Root scrolling uses the actual viewport origin.
Repeated model subheading IDs are occurrence-based, so anchoring falls back to
a unique enclosing source-range heading when insertion changes those IDs.
All dynamic text still goes through the existing escaped Markdown renderer.

## Additive artifacts, identities, and recovery

No database or task-model migration is required. New artifacts are:

- `partial_note.json`, schema version 1: source revision, generation revision,
  document revision, `status=draft`, `verified=false`, and completed sections.
- Each section: stable ID from the source revision and canonical grid time
  bounds; canonical source-window indexes/ranges; content revision; completed
  Markdown; `kind=vision_batch`, `summary_generated=true`,
  `status=evidence_pending`, `verified=false`.
- `draft.partial.md`: recoverable reader projection. Existing `draft.md`,
  transcript files, media, prior published notes, and personal editions remain
  separate. Existing `note_path` can point to this generated draft with
  `summary_source=partial-draft` until final publication.
- `partial_section_ready`: a notification on the existing versioned task SSE
  log, with its existing monotonic absolute cursor. Details contain only IDs,
  revision, artifact name, count, and false verification status, not draft text.

The generation revision hashes the same exact batch request/cache identities
already used for the vision cache: prompts, model/endpoint, canonical window
bounds, and image bytes. Resume retains matching sections. A changed generation
drops stale projected sections when its first current batch arrives; original
cache/source bytes remain. An attempt token rejects a late callback from a
previous attempt. Metadata timestamps advance for changed readable content so
the existing desktop refresh actually reloads it. Duplicate cached delivery
does not churn that timestamp or emit another notification, even after a long
event history.

Persistence precedes notification. A fresh callback can rebuild malformed
known-schema JSON or invalid UTF-8 Markdown from valid completed cache entries.
Saved sections must still have the correct identity, content hash, finite
ordered bounds, and evidence-pending status. Unknown future numeric schemas
are preserved. Storage failures stop further work rather than claim a draft is
ready; successfully completed batch cache entries remain available for retry.

Cancellation is checked before publication and before further batch dispatch.
Cancellation during projection records a cancelled summary stage. Requests
already in flight retain the existing provider-cancellation limitations.

Optional callback/cache arguments are adapted from the callable signature
before execution. An internal `TypeError` must propagate, never cause a second
summary/provider invocation. Five legacy tests now patch their exact existing
functions directly so signature inspection sees the same legacy contract,
instead of a mock's generic `**kwargs` wrapper. Dedicated tests cover both a
legacy adapter and an internally failing adapter invoked exactly once.

For rollback to an older release, first repoint an incomplete task using
`draft.partial.md` to its retained `draft.md` with
`summary_source=transcript-draft`, then rebuild its local index. Preserve the
partial JSON/Markdown and vision cache. Do not change completed `note.md` tasks
or personal editions. This step is necessary because an older release does
not know the new draft's retrieval exclusion. A synthetic round-trip test
checks the task record and this pointer-only rollback without deleting or
rewriting source/generated bytes.

## Acceptance evidence and remaining scope

The offline synthetic-provider tests verify completed text is readable before
later calls/merge, out-of-order completion, cache replay, interruption repair,
monotonic replay, stale-attempt/generation rejection, final-quality rejection,
cancellation, actual library/evidence and task-QA projections, and actual
Markdown export routes. They use the repository's external-network guard;
no real provider or user input is involved.

Cloud checks on 2026-10-09 after integrating main `519d8af`:

- Full `scripts/test-backend-offline.py`: 939 tests passed, including all 16
  progressive-section cases and the pointer-only rollback case.
- The subsequent strict saved-bound guard rejects JSON booleans as numeric
  positions. All 17 focused progressive-section tests passed after this change.
- All web Node tests: 115 reported entries passed, including the reader/SSE
  and generated-draft explanation checks.
- Scripts tests: 153 passed, with three existing Windows/PowerShell skips.
- Actual architecture script, Python compile, JavaScript syntax, whitespace,
  and the UI fixture's no-browser self-test passed.

The committed Windows Edge fixture exercises the shipped UI with mocked
task/edition/EventSource responses: source-position retention with repeated
subheadings, duplicate-event DOM/selection stability, escaped hostile text,
readable sections after merge failure, and an explicit simulated final-success
transition. It writes a report even on failure. Browser execution belongs to
the Windows CI run; local browser execution is not claimed.

The existing 5/30/60/180-minute reference-outline SLO remains a synthetic
caption-to-excerpt benchmark. It measures neither generated-section latency
nor real network/model quality. No budget was raised.
At 20 samples per duration on this cloud machine, outline-visible p95 was
0.0598 / 0.1059 / 0.1713 / 0.4128 seconds for 5 / 30 / 60 / 180 minutes.
After-transcript p95 was 0.0139 / 0.0183 / 0.0194 / 0.0340 seconds. All existing
reference budgets passed; these numbers do not measure generated sections.

Still open: progressive text-provider topic chapters, token-stream adapters,
extension sidepanel generated-section rendering, per-section verified labels
tied to final evidence results, stable source sections with in-place visual
enrichment instead of an appended completed-batch area, separate vision/merge/
verification timings, and richer dynamic route estimates. The final merged
note still replaces the draft edition once through the existing final gate.
