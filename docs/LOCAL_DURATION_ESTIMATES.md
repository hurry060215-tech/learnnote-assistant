# Local duration reference ranges

This is a bounded part of issue #148. It provides optional task presentation
projections and the same references in the default reader's processing steps.
`duration_estimate` retains the original after-transcript boundary. The new
`whole_task_duration_estimate` measures one current processing attempt, described
below. These replace the old invented whole-task `eta_seconds` formula
with `null` for unfinished tasks. Terminal tasks keep the legacy zero value;
the default reader does not display a countdown for terminal tasks.

## What is actually measured

The scope is **work after transcript readiness**, until the successful final
note and its local checks have been saved. It includes remaining frame/OCR,
vision, summary, merge and output work that the selected route actually runs.
It excludes prior queue wait, download, media preparation and transcription.
It is not a whole-task prediction, provider price or completion deadline.

There are two explicit start hooks: after the media pipeline saves its
transcript draft, and before transcript-only note generation (including a saved
transcript retry). The caller supplies the actual options, observed transcript
source and media duration. We do not infer duration from the last subtitle cue.
Caption-only extraction, page text, unrecognized transcript sources, warning
transcripts and unknown duration do not create samples. Before this boundary,
the estimate is unknown.

The interval uses an in-process monotonic clock. The finishing callback must
still own the current attempt; that attempt and task must both have succeeded,
without cancellation, task errors or failed/cancelled stages. Completed summary
and verification timings are required. The duration is not a sum of nested
stage timings. Faults in this optional observation cannot fail the pipeline.
Lost process clocks, including a backend restart, are unknown, never recovered
from wall timestamps. Repeating a start callback does not reset its clock.

## Matching and the range policy (version 1)

Only successful new measurements qualify. Existing metrics and TaskRecord
schemas remain unchanged; old tasks are not backfilled or reinterpreted.

- Exact match: measurement schema/scope; media-to-note or transcript-to-note
  route; actual supported subtitle/ASR source; task source type; declared
  CPU/CUDA and compute mode; selected model, provider endpoint and complete task
  processing options. Model credentials are excluded. `auto` device selection
  and ambiguous/credential-bearing endpoint URLs remain unknown. The actual
  endpoint and model must already be explicit in the execution options;
  unresolved legacy/saved-connection defaults remain unknown rather than being
  labelled with a potentially different configuration default.
- Input duration must be between 0.8 and 1.25 times the current media duration.
  This is a nearby-duration cohort, not a claim that runtime scales linearly.
- Use at least five distinct other tasks, at most the 30 most recent eligible
  successes among the bounded history read. Repeated attempts count once per
  task; the current task never trains its own estimate.
- Evidence expires after 30 days. Missing, malformed, non-finite, zero,
  negative, future-dated or greater-than-24-hour sample durations are rejected.
  Chronologically reversed wall timestamps are rejected too. Wall timestamps
  support freshness only, not elapsed-duration calculation.
- The reference interval is floor(0.75 × minimum measured time) through
  ceil(1.25 × maximum measured time). No linear duration extrapolation, trimmed
  outlier removal, progress percentage or provider benchmark is used.
- Remaining time subtracts the current monotonic elapsed interval. The lower
  bound may reach zero. At or beyond the historical upper bound, remaining time
  becomes **unknown**, labelled overrun. The historical reference stays visible;
  it is never silently extended or frozen at “0 seconds remaining.”

The 25% padding and minimum sample count are conservative engineering policy,
not a statistically calibrated coverage probability. We make no “90% accurate”
or similar confidence claim. Synthetic tests establish the calculation and
exclusion rules, not predictive accuracy on real media. Any future calibration
claim requires independently held-out local outcomes, a disclosed evaluation
period/cohort and measured interval coverage and overrun rates. Changing the
policy or measurement boundary requires a schema version change so incompatible
history cannot be silently mixed.

Hardware identity is intentionally not collected. For this original scoped
projection, matching a declared device
mode does not establish identical hardware or remote-provider load. A moved
data directory, changed hardware/model implementation, cache warmth, provider
throttling and other load can invalidate historical usefulness even within a
matching cohort. The UI calls this a historical reference and says actual time
may exceed it. The newer current-attempt projection uses a stricter same-process
cohort; provider-price calibration and real-media prediction accuracy remain open.

## Storage, bounds and privacy

The additive `duration_evidence.json` sidecar keeps up to 20 newly observed
attempts per task. It does not modify `pipeline_metrics.json` history. Each new
measurement saves only its attempt ID, timestamps, monotonic interval,
allowlisted route/source/mode fields, media duration and opaque SHA-256 option
identities. The hash distinguishes endpoints, models and instruction settings
without storing their text; it is not an anonymization guarantee or credential
store. A separate opaque input identity detects changed media/ranges within the
current attempt, and is not used to match unrelated history tasks.
No keys, task titles, content, URLs, paths, machine IDs or network probes
are recorded there. No database, dependency or permission is added.

The read-only history scan inspects at most 256 directory entries and 64 KiB per
sidecar, without following task-directory or sidecar symlinks. A 30-second
in-process cache bounds repeated reads; a newly finished measurement clears it.
The bounded scan may miss eligible tasks in a large directory, in which case it
may report insufficient history. It never invents samples to fill a gap. Invalid
history files are skipped; a current evidence or reader failure reports unknown.

The API exposes only aggregate ranges/count, current attempt identity, current
elapsed time, a timestamp and fixed reason codes. It never exposes history task
IDs, names, paths, endpoints, option hashes or personal content. The UI rejects
malformed, more-than-60-second-old and mismatched-attempt snapshots, and suppresses
estimates on queued, stopping, failed, cancelled or successful tasks. The range
is a snapshot refreshed with task metadata, not an independent countdown timer.

## Verification and remaining acceptance

`backend/tests/test_duration_estimates.py` uses temporary synthetic histories
and fake clocks. `web/tests/progress.test.mjs` covers honest display, overrun,
stale snapshots, retry identity, cancellation, invalid values and legacy null
ETA handling. The existing Windows Edge progressive-sections fixture now checks
the measured reference, progress-only overrun and failure display using mocked
task APIs. Run it through the normal Windows UI CI; a syntax check is not an
Edge run. No paid provider, model, real user data or local browser execution is
needed for the offline contracts.

Local validation on 2026-10-10, based on `c184caec`: 1,164 backend tests passed
with the offline network guard and fresh synthetic `/data` storage, including
33 duration contracts; all 168 Node web contracts passed; both progressive
fixture self-test scenarios passed without launching a browser. Backend
compilation, the changed JavaScript syntax checks and `git diff --check` passed.
Actual Windows Edge visual acceptance and held-out real-media calibration were
not run locally and are not established by these results.

## Preflight is not an elapsed-time measurement

Local-media preflight reports duration and integrity but returns `estimated_seconds: null`.
Media duration alone does not identify the selected hardware, model, subtitle route,
queue, or provider latency. The classic confirmation view also ignores legacy point
values and shows that whole-task timing is unknown. This does not change the scoped,
measured after-transcript interval in the current workspace. Preflight alone does
not satisfy the new current-attempt measurement contract either.

## Current processing attempt reference (version 1)

`whole_task_duration_estimate` is a separate aggregate with scope
`current_processing_attempt`. Its independent monotonic clock begins at the
recorded enqueue for this attempt (`accepted_enqueue`), or at the explicit
pipeline attempt start (`attempt_start`) when no valid enqueue clock exists.
The latter explicitly excludes queue time. Both finish only after the successful
note and local checks are persisted. The interval includes all actual intervening
work and gaps; nested stage durations are never summed. User confirmation,
earlier failed attempts, downtime and waiting before the current recorded enqueue
are outside the boundary. A retry is one new attempt, not the original task's
end-to-end duration.

The clock may start before download or transcription, but an estimate is not
published until the actual supported transcript source, media duration, selected
model and processing route are known. The app does not guess which caption/ASR
route will succeed. Before that point, missing or incompatible evidence means
unknown. This does not provide an estimate during the initial download or initial
transcription and does not claim to close every criterion in issue #148.

History must contain at least five distinct successful tasks in the same
backend process and compatible processing context. A random process cohort
separates runs without recording a machine identifier or probing hardware. A
backend restart therefore starts a new whole-attempt cohort; previous sidecars
are retained and cannot masquerade as measurements on the new execution device.
Declared CPU/CUDA and compute modes, explicit selected endpoint/model/options,
known model capabilities, actual source, nearby duration, observed work route and
reuse state further partition the cohort. Unknown device selection or capability
is not evidence of compatibility. Remote provider load and changing local load
can still vary within a cohort; no accuracy or deadline is promised.

Selected learning ranges and local OCR currently remain unknown because their
clipping/OCR preparation and reuse are not fully observed by this contract.
Visual routes additionally require locally known model capability and no prior
frame/vision cache. Successful output that used a fallback, repair or unexpected
cache path cannot train a fresh-route estimate. These exclusions reduce available
samples deliberately; they do not start extra work to obtain timings.

The separate bounded `whole_attempt_duration_evidence.json` sidecar preserves
the original after-transcript evidence and pipeline metric schema. Old stage
metrics and after-transcript intervals are never backfilled into whole-attempt
samples. Only aggregate range/count, current attempt, boundary, elapsed time and
fixed reason codes reach the UI. No task content, endpoint, model name, history
identifier, credential or machine identity is exposed. Faults in this optional
observation must not change processing, cancellation, model calls or publication.

A bounded in-memory registry remembers at most 256 tasks whose whole measurement
was successfully saved by this process. Only their sidecars are considered,
with the existing file-size and cache bounds. Thousands of older task folders
therefore cannot hide the new eligible cohort. Deleted, linked, corrupt or
incompatible registered files are ignored; restarting discards the registry.
No catalog migration or extra disk index is needed. Existing or dangling
sidecar symlinks are left intact rather than replaced with fresh measurements.

The same conservative empirical envelope and minimum-sample policy apply. The
remaining reference subtracts only live monotonic elapsed time. At the upper
bound it becomes unknown rather than freezing at zero or extending a deadline.
Missing clocks, retry identity changes, cancellation, failure and stale snapshots
invalidate it. When whole-attempt history is unavailable, an eligible older
after-transcript reference may still appear under its original explicit label;
an overrun whole-attempt estimate never silently changes to a narrower countdown.

Synthetic unit and in-process ASGI/API tests establish interval provenance, exclusion
rules and data preservation; they do not establish real-model prediction quality.
The existing progressive-sections Edge acceptance exercises the new reference,
overrun and retry through production UI assets with synthetic API/SSE responses,
including 1440/390px in both themes. Actual browser evidence is recorded with the
pull request; fixture self-tests alone are not a visual pass.
