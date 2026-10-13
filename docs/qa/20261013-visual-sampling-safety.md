# Preserve sampled visual changes and published evidence

Related roadmap issue: #149. This fixes sampling correctness and cache safety;
OCR-assisted request reduction and whole-film quality acceptance remain open.

## Reproduction and behavior

The old 8×8 grayscale hash plus mean-luminance rule classified small graphic,
color, or subtitle/operator changes as duplicates. It could delete an image that
FFmpeg had already sampled. The old planner could also omit the final seekable
second, or let playback anchors consume the entire endpoint budget.

The new policy (`adaptive-batch-v3-exact`) removes only encoded-byte SHA256-equal
images between periodic coverage anchors. Different encodings can remain as
extra frames; approximate visual equality never authorizes deletion. Mandatory
start/tail, scene/context, and playback-anchor samples bypass deduplication.
The full timeline is sampled before limiting the plan. First and last seekable
seconds have priority when at least two distinct samples fit; missing endpoints,
omitted anchors/coverage/scene context, and failed extraction have explicit
metrics. Warnings distinguish partial sampling from an absence of all slices.

Limits remain: the configured frame budget, 32-image maximum FFmpeg batch,
existing 80-grid model-selection ceiling, provider image-count limits, and
existing vision concurrency. Keeping more changed frames can increase disk use,
grids, and model requests up to these existing limits. No reduction percentage
or quality guarantee is inferred from duplicate counts. Intermediate changes at
unsampled times, lossy extraction details, and grids outside model selection can
still be missed.

## Prior evidence and recovery

- New caches use schema 3 and a policy/source/plan-bound cache filename. Existing
  legacy caches and images are left intact.
- Images are staged before publication. Actual-byte SHA256 filenames preserve
  old frame/grid URLs when sampling or grouping changes. Existing target bytes
  are checked, never replaced. Hardlink publication is atomic where supported;
  unsupported-link volumes use exclusive copying, cleaning only this call's new
  file on a caught copy error. The fallback is not atomic: process death can
  leave an unreferenced partial target, and later conflicting bytes fail closed.
- A matching complete cache validates owned filenames, hashes, and duplicate
  decisions. Missing endpoint/other decode failures never become permanent
  duplicate skips. Incomplete extraction retries on the next attempt.
- Published task window mappings are pinned, including after a policy upgrade.
  Reuse requires matching media and frame hashes, owned paths, and agreement
  between the index and retained task windows/grids. Missing, incompatible, or
  mismatched evidence stops before extraction rather than silently remapping
  W001. Resume retains these references; text/OCR-only retries preserve them
  without sending their grids to the model.
- To adopt new sampling or grouping for an existing published task, use the
  existing new-task action backed by `POST /api/tasks/{id}/rerun-from-media`.
  The original task remains independently readable. This is not a general
  versioned history/export migration or a repair of already damaged references.
- Cancellation checks run at extraction batch/grid boundaries and before
  publishing the visual index. Temporary extraction/grid directories are
  removed on exceptions. An active FFmpeg batch can finish before cancellation
  is observed; there is no promise of instant process interruption.

## Controlled local experiment (2026-10-13)

An 8-second, 640×360, lossless FFV1 synthetic video contains small graphic
changes at seconds 2 and 7. It is 3,467 bytes; SHA256:
`6a6bfa31d3a2740b3b4035933a8b0a9c1f49e6fa1c617b1102d5c1e61844668f`.
No OCR or model was executed. The two policies ran against identical bytes.

| Measurement | Prior policy | New policy |
| --- | --- | --- |
| Planned timestamps | 0, 2, 4, 6 | 0, 2, 4, 6, 7 |
| Retained timestamps | 0, 6 | 0, 2, 4, 7 |
| Retained encoded frame bytes | 6,862 | 14,447 |
| FFmpeg batches / single-frame fallbacks | 1 / 0 | 1 / 0 |
| Extraction metric | 129 ms | 131 ms |
| Whole extraction wall time | 280 ms | 285 ms |
| Built / selected grids | 1 / 1 | 1 / 1 |
| Actual model requests | 0 | 0 |

These are single-run timings, not a performance benchmark. The larger retained
byte count is an intentional safety tradeoff. The warm new cache used no
extraction batch. Controlled regressions also cover a same-hash small operator
change, budgets 0/1/2/3/60, excess anchors, full-timeline distribution, fractional
short media, old/new cache recovery, partial failure, cancellation, publication
failure, unsupported-hardlink volumes, resume, and unchanged window identities.

This evidence does not establish real OCR accuracy, semantic equivalence, a
50% request saving, or coverage of the user's four-hour video. No private media,
credentials, new model provider, or paid request was used.
