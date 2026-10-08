# Local queue admission and resource verification

Issue #132 remains open for explicit queue-priority/pause controls. This change
repairs global admission, independently bounds download work, and provides
reproducible concurrency/cancellation evidence without provider credentials.

## Configuration and compatibility

Each data directory has durable SQLite intent records and OS-backed lane
leases. Defaults are one heavy task, one subtitle/summary task, and one
download. Configure `LEARNNOTE_HEAVY_CONCURRENCY`,
`LEARNNOTE_LIGHT_CONCURRENCY`, and `LEARNNOTE_DOWNLOAD_CONCURRENCY` to integers
1–4 before starting the service. Invalid values fail startup. All processes
sharing a directory must use the same policy; restart them together when
changing it. `LEARNNOTE_LOW_RESOURCE_MODE=1` clamps all budgets to one without
dropping queued work. Existing task-level low-resource options additionally
reduce frame/vision work; they do not silently change other tasks' budgets.

Download-only tasks occupy a download slot. The download stage inside a heavy
task uses the same slots and checks cancellation while waiting, avoiding
unbounded downloads across lanes. Already-held slots are reused without
recursive locking. Queue position is calculated per lane; the desk shows the
current lane's concurrency limit. FIFO is shared across processes within each
lane; independent light/download lanes prevent starvation by heavy tasks.

An intent waiting for another process's lease remains `queued`, so cancelling
does not wait for the running task. Only successful lease acquisition and an
atomic FIFO claim transition it to `running`. Cancellation and claims race
through conditional database writes. Future completion is owned by the active
worker, preventing competing workers from finishing the same Future twice.
Recovery acquires every lane/slot before resetting orphaned running records.
Browser cookies, keys and callback payloads remain in memory and require an
explicit resume handoff after restart.

## Reproduction

- `python scripts/scheduler-reliability.py --output-dir build/queue-gate`
  submits five mixed intents, proves peak 1 in each of three independent lanes,
  reuses duplicate Futures and reopens the durable journal.
- `PYTHONPATH=backend python -m unittest discover -s backend/tests -p
  test_queue_admission.py -v` covers cross-instance FIFO, configured two-slot
  sharing, invalid settings, low-resource retention, occupied-slot cancellation,
  nested stage reuse and exception cleanup. Unhandled worker-thread exceptions
  fail the tests rather than being printed and ignored.
- `python scripts/queue-asr-reliability.py --model-dir <local-tiny-model>
  --speech-file <local-jfk.flac> --output-dir build/queue-asr-proof`
  requires existing public fixtures and performs no downloads. It uses the
  repository offline guard and pre-initialization native telemetry opt-outs.

Cloud proof on 2026-10-08: public `Systran/faster-whisper-tiny` plus OpenAI
Whisper's public `tests/jfk.flac`, converted to a 12-second generated video.
Five tasks submitted: three real ASR tasks and one prebuilt-subtitle task
completed the media/transcript/draft/note pipeline; one pending task cancelled.
Heavy and light lane peaks were each 1. Cancellation took 0.0004 seconds; all
four completed in 7.04 seconds. Process RSS peak was 383,004,672 bytes; measured
CPU peak was 194.723% across CPU cores. Resource reports were written for all
four completed tasks. The summarizer was explicitly a deterministic reference
adapter, not a paid/remote model or model-quality benchmark. No remote calls.

The resource monitor measures this process, not total child-process RSS or a
low-end physical device. This 12-second reference is not a multi-hour resource
or first-note p95 claim. The initial harness attempts failed on an incorrect
report field and an unrecognized reference-source label; only the corrected
run above is counted as passing. Backend regression: 733 tests, no skips.
