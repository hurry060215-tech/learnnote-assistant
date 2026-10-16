# Offline acceptance measurements, 2026-10-16

Product baseline: `b590e55169cebd4ca34a7312b16fef1aa3ecec01` (v0.2.15).
These Linux x86_64 cloud measurements use self-generated inputs and no model
service. They supplement #148/#149/#151; they do not close those issues.

## Caption outline and cancellation

`scripts/progressive-slo.py --repetitions 20` exercised the real queue, storage
and draft path with complete synthetic timed captions and a deterministic final
summary adapter. Nearest-rank p95 time to source outline was 0.0565 / 0.0879 /
0.1149 / 0.2612 seconds for 5 / 30 / 60 / 180 minutes. After-transcript p95 was
0.0169 / 0.0167 / 0.0171 / 0.0255 seconds. All 80 executions passed the existing
10-second outline and 5-second reference-draft gates. This is not time to an
AI-generated semantic chapter, UI rendering, queue contention or final quality.

`scripts/cancel-reliability.py --duration-seconds 180` ran a real local processing
thread and cancelled it in 0.163 seconds with no late processing phase and a
persisted resource report. It exercised cancellation near processing start,
not cancellation during every remote provider stage or subsequent recovery.

## Media resource matrix

`scripts/long-video-reliability.py` used generated 320×180, 1-fps H.264/AAC media,
40 frames, 3×3 grids, a 512-MiB parent-RSS cap and 512-MiB free-disk floor.
Intervals were 45 / 90 / 270 seconds. Every run covered the beginning and tail.

| Duration | Generate + extract + grids | Parent peak RSS | Reused-input maximum process RSS |
| --- | ---: | ---: | ---: |
| 30 minutes | 8.521 s | 39.98 MiB | 269.62 MiB |
| 60 minutes | 14.367 s | 40.12 MiB | 278.82 MiB |
| 180 minutes | 41.326 s | 39.86 MiB | 312.38 MiB |

The last column is a separate extraction rerun with existing media, measured
by a fresh Python parent using `resource.getrusage(resource.RUSAGE_CHILDREN)`
after waiting for the benchmark process. On Linux its `ru_maxrss × 1024` includes
the waited process family (including FFmpeg). It is the maximum RSS of an
individual process, **not** the peak simultaneous sum across all processes.
User/system CPU seconds and wall times are retained in the JSON. These rows
do not enforce whole-process-tree memory or CPU budgets, do not measure normal
resolution real lessons, and contain no ASR, OCR or vision-model execution.

## Actual local OCR

`scripts/ocr-fixture-benchmark.py` ran RapidOCR 1.4.4 against six self-rendered
fixtures. English, Chinese and code text matched exactly. The slide lost a
space (similarity 0.941). The formula `E = mc²` became `E 二 mc2` (0.714), and
the low-resolution `LEARNING RATE` became `LEA` (0.375). These are recognition
errors, preserved in the report; neither expected text nor thresholds were
changed to make them correct.

Both degraded cases contained an uncertain OCR line. All OCR lines remain
unreviewed, with review required; no recognized line becomes a verified claim.
Six first-pass engine calls took 5.235 seconds; repeat-cache access took 0.001
seconds with zero engine calls. The report's pass means cache/privacy contract
pass, **not** recognition accuracy or vision-model quality pass. All six fixture
fonts were available. A first attempt using the test-only environment lacked
the optional OCR dependency and did not run; the actual result uses the
existing OCR-capable environment with the repository's markdown-it-py 4.2.0.

No remote vision calls were made. A 50% remote-call reduction with unchanged
fact coverage is still unproven; cache savings cannot establish it.

## Evidence files

- [Outline report](20261016-offline-measurements/progressive-outline.json)
- [Cancellation report](20261016-offline-measurements/cancel.json)
- [Media, digests and process-family counters](20261016-offline-measurements/media-matrix.json)
- [OCR expected and actual text](20261016-offline-measurements/ocr-fixtures.json)

Machine-local paths were replaced with descriptive relative names. Exact media
SHA-256 values are retained. The generated images/media contain no real user
content or credentials. The existing reference scripts are the reproduction
entry points; use a new isolated output directory to avoid warm-cache results.
