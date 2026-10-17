# Task-list projection latency: bounded first correction

## Evidence

The retained Windows 80-sample progressive run at `1dc3cbc` shows draft display
waiting on the full task list. Sample 65 received its native draft event at
1249 ms; `/api/tasks` completed its body at 6285 ms; only then was the selected
edition requested (6295 ms), received (6333 ms), and observed (6376 ms).
This is request ordering evidence, not a browser main-thread profile.

An isolated Linux replay used the existing complete-caption fixture, actual
admission and queue, and held synthetic final summary. It retained all 80 tasks
(20 each at 5/30/60/180 minutes), checked every source cue, and made no media or
provider requests. The full response was 2,635,007 UTF-8 bytes. Single-list wall
and CPU were approximately one second; two simultaneous lists took 2.24 seconds
and four took 5.47–5.59 seconds. RLock waits rose from under 0.5 ms idle to
1.04–1.38 seconds per request with four readers. These are Linux observations,
not measurements of Windows lock waits or a hosted SLO pass.

The original list reads each manifest seven times in this fixture (560 total),
reads each transcript four times (320), checks media provenance ten times per
task, and rereads the complete queue table 80 times. No retained data is removed
or shortened by this correction.

## Scope and contracts

- Keep stale-task reconciliation, title repair, and deferred-handoff expiry
  rechecks unchanged, including their existing lock order.
- `task_payload` still owns `public_summary_task`. It creates a local media
  evidence object bound to that exact record, generation, update and path identity.
  Existing ownership/provenance and signature checks execute on first access.
  No evidence object survives the payload call; unrelated actions keep fresh
  validation defaults. No new lock spans a payload or the whole list.
- Read and order one queue snapshot per list; apply the existing per-task
  projection to it without mutation. Standalone queue reads remain fresh.
- Preserve the complete public task payload, captions, claims, diagnostics,
  recovery/actions, QA and artifact checks. No pagination or persistent cache.
- Preserve transcript-reader semantics in this first slice.

## Actual media-and-queue-only comparison

The same retained 80-task directory was measured sequentially using exact
`1dc3cbc` source and this implementation in separate processes after other local
CPU-heavy validation finished. All 1,520 retained task files had identical
SHA-256 hashes before and after both measurements. The complete response matched
the frozen pre-edit response, excluding only `observed_at_unix_ms`; both responses
were 2,635,007 UTF-8 bytes. No caption or artifact was omitted.

- Three single-list trials: baseline 0.840–0.951 s (median 0.856), corrected
  0.574–0.673 s (median 0.662); thread CPU closely matched wall time.
- Two concurrent requests: baseline 2.237–2.301 s, corrected 1.515–1.577 s;
  total process CPU 2.434 versus 1.773 s.
- Four concurrent requests: baseline 5.176–5.620 s, corrected 3.155–3.287 s;
  total process CPU 6.322 versus 3.639 s.
- Media-path resolution calls: 800 to 80. Complete queue-table reads: 80 to 1.
  Manifest/transcript/claim/inventory reads remain 560/320/80/80 and total
  JSON-read UTF-8 bytes remain 27,271,940. Transcript work was not optimized.
- RLock acquisitions remain 880 per list. Four-reader cumulative waits rose
  from 1.162–1.440 s to 1.624–2.123 s despite lower CPU and wall time. This slice
  does not solve task-state lock contention.

A subsequent real 180-minute task was admitted with the original 80 retained.
During four concurrent full 81-task API lists, its cancellation response took
0.299 s and cancellation plus callback completion took 0.416 s. The four lists
took 4.159–4.390 s; every original task file remained unchanged. The additional
cancelled task was retained too. These TestClient/Linux results are not browser
or Windows acceptance measurements.

The explicit interface adds eight lines to `main.py` (4,217 total, existing
4,270 cap unchanged) and a 47-line bounded evidence module. Existing public
payload names and defaults remain unchanged. The new module guard is 90 lines;
no existing size or aggregate cap increases.

## Separately confirmed open race

The original `read_transcript(task.id)` rereads the manifest even when its caller
owns an older `TaskRecord`. A deterministic two-thread barrier reproduces an
`attempt-a` payload containing transcript provenance from `attempt-b` after a
retry replaces the manifest and transcript. This pre-existing mixed-generation
artifact race is not resolved or cached by this correction. A captured-generation
artifact contract needs separate review; an optimization must not hide it with
empty evidence, broad locks or unbounded retries.

This correction does not close all architecture or progressive-performance
acceptance. Hosted Windows full-retention timing and lifecycle checks remain
necessary after integration.
