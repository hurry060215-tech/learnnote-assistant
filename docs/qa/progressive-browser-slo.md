# Complete-caption browser latency reference gate

Run on an isolated Windows runner with Microsoft Edge, the committed Python test
dependencies and Playwright installed:

```powershell
$env:LEARNNOTE_ACCEPTANCE_PYTHON = "python"
node scripts/progressive-slo-api-acceptance.cjs build/progressive-slo-ui
```

An optional `LEARNNOTE_ACCEPTANCE_BROWSER` selects an installed Edge executable.
The gate validates a canonical Edge executable file and passes that exact path
to the owned browser launch. It records that launch path plus the instance version,
user-agent and brands, and rejects a non-Edge executable. A missing or invalid
explicit override fails without selecting another browser. Use a separate runner/job, sequentially,
without heavy concurrent media tests. The hosted job timeout is 30 minutes.

## What is measured

The matrix has 20 attempts each for complete 5, 30, 60 and 180-minute synthetic
captions. Every task uses the real HTTP admission, durable queue, transcript and
draft files, native SSE, shipped reader and browser layout. The final summary
adapter waits until the reader is observed; it then produces deterministic text.
No source download, ASR, vision inference or provider request is allowed. The
owned synthetic data directory has the existing automatic update-check and
automatic download preferences disabled before app startup. Automatic release
checks are excluded from this reference gate; production defaults are unchanged.
The real startup update-status response must succeed locally without a forbidden
network attempt. An API regression separately forces a check and verifies denial.

Latency starts immediately before the browser submits `/start`. It ends after
the actual time-based outline heading and its first literal source excerpt are
visible, unobscured and in the viewport, including a harness scroll using the
reader's normal scroll margin and two animation frames. This is a source-excerpt
reading outline, not an AI-inferred thematic chapter or verified final summary.
The native `draft_ready` SSE event must also be observed. CDP request IDs bind
events to the exact same-origin task stream URL; ordinary server event bodies
need not repeat the task ID. Explicit conflicting identities are rejected, native
event IDs are retained, and obsolete request/session bindings are discarded. Each persisted transcript
and outline is checked against the complete declared reference duration, including
the final cue and section. Ancestor opacity and missing/hidden source text cannot
pass readability.

The transcript-to-visible acknowledgement is a conservative upper bound measured
on one backend monotonic clock, including browser observation and local ACK
transport. It must be at most five seconds for every measured attempt. The
submission-to-readable p95 uses nearest rank and must be at most ten seconds for
each duration. All 20 attempts are required; slow values are retained, failed or
invalid rows cannot be filtered into a passing cohort, and unrun cohorts remain
explicitly incomplete after an infrastructure/assertion failure.

Application startup, capture and deferred confirmation finish before the timed
submission. Each sample has new task/artifact state, but shares an initialized
backend/browser context. The first sample is identified separately. OS and HTTP
caches are not artificially cleared. This does not measure cold application boot,
provider latency, model quality, queued contention, or the video/vision route.

## Cancellation and recovery

An additional untimed lifecycle case cancels while the draft is readable. The
real callback must acknowledge and drain within two seconds, with no further
continuation and unchanged transcript/subtitle/draft hashes. An explicit summary
retry obtains a new generation. The fixture process is then killed and restarted
against its owned data directory. Real startup recovery must retain that task ID,
accepted retry generation, queue sequence and source hashes. Desktop and 390-pixel
mobile captures show the retained draft; the released continuation must complete.
This demonstrates recovery of that accepted intent, not reuse of every computation
or cancellation latency for all other processing stages.

## Evidence and failure handling

`report.json` retains attempted rows, phase events, source coverage, geometry,
native SSE records, bounded same-origin API request/response metadata, browser
identity and lifecycle checks. The accepted task ID is saved before reader
navigation or stream observation, including on preparation failure. Eight
planned screenshots and
`backend.log` (capped at 1 MiB with an explicit truncation flag) stay in the output
directory. Task data is generated separately in an owned temporary directory and
must not be uploaded. The fixture refuses nonempty fresh directories and unmarked
resume directories. Forbidden-operation evidence survives process restart.

On failure, a viewport-only `failure.png` and bounded page/fixture/task state are
attempted before cleanup. These optional diagnostics each have a deadline; their
failure cannot replace the primary assertion or skip cleanup. Network diagnostics
retain host/path and bounded code locations, without headers, query values or
credential-bearing URLs. Denied external requests remain gate failures; disabling
automatic update checks does not disable the offline guard.

Failures remain nonzero, including cleanup failures. Report-write failures cannot
skip browser/backend cleanup or replace the original assertion. A successful local
API contract run is not a browser SLO result; only the hosted report establishes
that result.
