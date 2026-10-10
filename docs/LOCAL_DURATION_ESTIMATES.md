# Local duration reference ranges

This is a bounded part of issue #148. It adds an optional task presentation
projection, `duration_estimate`, and the same reference in the default reader's
processing steps. It replaces the old invented whole-task `eta_seconds` formula
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

Hardware identity is intentionally not collected. Matching a declared device
mode does not establish identical hardware or remote-provider load. A moved
data directory, changed hardware/model implementation, cache warmth, provider
throttling and other load can invalidate historical usefulness even within a
matching cohort. The UI calls this a historical reference and says actual time
may exceed it. Whole-task estimates and provider-price calibration remain open.

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
