# Recorded pipeline stage durations

The desk timeline reads local `stage_timing` events from the current attempt.
These are elapsed monotonic intervals, not estimates or sums of provider CPU
or request times. TaskRecord phases and archive payload schemas are unchanged.

| Stage | Recorded boundary |
| --- | --- |
| queue | Current accepted in-process enqueue, after its durable intent is committed, through worker callback dispatch. Includes waiting for the worker lease; excludes user confirmation and callback prelude. |
| download | Existing media download boundary, separate from media normalization. |
| transcript | Existing subtitle parsing / transcription preparation boundary. |
| frames | `extract_visual_evidence`: extraction, grids and enabled local OCR. The retained `visual` aggregate also includes the subsequent visual index and checkpoint work. |
| vision | Existing vision batch scheduling, collection and partial-section callbacks, including cache lookup and provider-slot waits. Measures the enclosing wall interval once, even when requests run concurrently. |
| merge | Existing vision merge provider-slot wait, request and response decoding; ends before the existing validation/repair routine. For multi-part text, measures only local assembly after all existing section calls. Short text has no merge. |
| verify | Existing local Markdown output checks, claim/source mapping, review markers and document assembly with their existing artifact writes. The subtitle route also writes the note within this boundary. This does not assert semantic factual correctness or add model verification. |

The existing `visual` and `summary` aggregate measurements remain available.
Their original scopes differ: media summary timing ends when the summarizer
returns; subtitle summary timing includes final local publication work. The UI
labels both as aggregates and explicitly says overlapping rows must not be added.
A successful summary stage no longer finishes the attempt prematurely: successful
attempt completion is recorded after the final checks and note persistence.

Queue markers are task-bound and consumed once. Duplicate enqueues/observers do
not reset them. A recovered job starts a new measurement at its new enqueue;
pre-restart waiting and downtime remain unknown. Cancelled jobs that never
dispatch have no executed attempt or completed queue measurement. Direct pipeline
calls outside the queue also leave queue timing unknown. The admission event
clears old timeline records immediately, and the desk SSE hub invalidates its
cached events when admission or attempt-start events arrive.

Observer and finalization callbacks capture an expected attempt ID at entry.
A late callback from an earlier attempt cannot write into or finish a retry; an
explicitly unknown capture stays disabled rather than capturing a later attempt.
Start, duration, completion and draft-metadata transactions share the existing
storage RLock so their identity checks and writes cannot interleave within a
process. Cross-process task ownership remains the durable queue claim and worker
lease contract; arbitrary direct pipeline calls from multiple processes are not
covered by this in-process lock. Provider work does not run under the lock.

Known skipped new stages omit duration rather than claiming a zero-second
measurement. Missing historical or failed-to-persist timings display as unknown.
Failures and cancellations inside a measured stage retain its elapsed interval
and original exception. New optional timing/event writes are best effort: storage
failure must not change an output, send another provider request, hide an original
exception or turn a published note into a failed task.

## Offline evidence

`backend/tests/test_stage_duration_provenance.py` uses synthetic clocks, source
files and dummy model responses under `scripts/test-backend-offline.py`'s network
guard. It checks enqueue/dispatch provenance, lease waits, duplicates, observers,
retries/recovery, nested/foreign tasks, cancellation, local frames/OCR, parallel
batch wall time, cache hits, merge/validation separation, short-text skips,
unsupported-vision fallback, unchanged request payloads/output and observer
failure isolation. Progress and event-hub tests cover the actual desk subscriptions,
unknown histories, retry invalidation and truthful local-check/aggregate labels.

These tests do not establish native Windows/Edge visual acceptance, performance
SLO evidence on real videos, or semantic note quality for all of issue #148.
