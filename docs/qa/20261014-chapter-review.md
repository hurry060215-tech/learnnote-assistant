# Bounded chapter review acceptance

Scope: the generated-note portion of #151. This does not close the broader
issue roadmap or establish real-model accuracy, long-video performance, native
desktop behavior, or OCR correctness.

## Behavior

- Partial generated prose keeps one chapter-level draft boundary. The existing
  claim map provides literal wording counts and review counts. These are not
  semantic or factual verification. Old drafts are not migrated.
- “核对章节概括” is a secondary tool for one current generated chapter or batch.
  Local preview shows the actual selected claims, complete selected source cues,
  coverage omissions, and saved provider/model destination before consent.
- Each explicit confirmation permits one model call with at most 12 claims,
  6,000 claim characters, 12,000 source characters, 2,000 output tokens and a
  30-second provider timeout. Pagination is manual with fresh consent. There are
  no automatic retries, fallbacks, repairs or model calls on open/preview.
- Source, attempt, chapter, revision and selected-connection bindings are checked
  before transmission and again before returning results. A quotation check only
  establishes attribution. Model opinions remain explicitly fallible.
- Results are ephemeral. No generated notes, originals, personal editions, claim
  maps or personal review records are rewritten. Existing final-note review
  markers and archive/export byte fixtures remain checked unchanged.

## Local checks

All inputs and provider responses were synthetic. No real credentials, remote
provider, cancelled video, user browser or user media were used.

- `python scripts/test-backend-offline.py`: 1,691 tests, 1 failure, 0 skips.
  The sole failure is the optional tokenizer overflow contract: expected
  `[[2, 3]]`, received `[]`. It was independently reproduced with the same
  interpreter and dependencies on a clean detached `2d49f805` worktree. The test
  remains enabled and unchanged; this run is not reported as green.
- `python -m unittest backend.tests.test_section_reviews`: 19 passed. Includes
  actual OpenAI SDK calls to a loopback fake server, explicit consent, exact
  preview payload, single-use tokens, concurrency, pre/post-call source and
  model invalidation, task ownership, redaction, malformed replies, altered
  numeric/negation quotations, manual pagination, timeout, rejected responses,
  redirects and HTTP 500 without retries, and unchanged note artifact bytes.
- The new routes are tested through the real application middleware: public
  Basic authentication, forbidden browser origins, extension pairing, allowed
  local origins, and the existing structured-write size budget.
- `python -m unittest backend.tests.test_task_archives`: 8 passed. The historical
  OpenAPI hash excludes only the three new chapter-review routes and two new
  schemas; every pre-existing operation/schema and all archive fixtures remain
  frozen. No authorization or generation/network gate was excluded.
- All 72 web and 71 extension JavaScript test files passed; all web/extension
  JavaScript syntax checks passed. New tests cover literal badges, escaped text,
  consent, manual next batches, stale responses, and close/reopen races.
- `python -m unittest discover scripts/tests -p 'test_*.py'`: 184 tests,
  181 passed, 3 platform-specific skips.
- `python -m unittest desktop.tests.test_desktop_launcher`: 28 passed.
- `python -m compileall backend/app` and `git diff --check`: passed.

## Actual-browser status

Local screenshot acceptance is **not complete**. Microsoft Edge is not installed
in this Linux environment. An installed Chromium subprocess could not start
because the execution environment rejected its process-singleton socket. The
separate cloud browser could not reach the executor's isolated loopback server.
No screenshot or geometric/aesthetic pass is claimed from those attempts.

The Windows CI workflow now runs `scripts/section-review-acceptance.cjs` against
`scripts/section-review-fixture.py`, an empty temporary workspace protected by
the existing external-network test guard and a local fake provider. It captures
light/dark states at 1280, 1440, 768 and 390 CSS pixels for ready, preview, selected
sources, confirmation, model results, expanded quotation and rejected response,
plus the partial reading view. It also checks manual batching, API request count,
dialog close/reopen, Escape/back/close, unchanged artifacts, horizontal bounds,
44px new controls, external requests and page errors. These screenshots must be
viewed before visual acceptance or merge; CI results will be recorded separately.
