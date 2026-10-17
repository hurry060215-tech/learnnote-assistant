# Synthetic visual-route process-tree measurements

This fixture observer supports the resource assessment in
[#149](https://github.com/hurry060215-tech/learnnote-assistant/issues/149).
It does not establish that issue's CPU/memory/disk/time budgets or its separate
50% remote-vision-call reduction with unchanged factual coverage requirement.

## Reproduce

Install the normal test dependencies and the optional benchmark-only dependency:

```sh
python -m pip install -r scripts/requirements.benchmark.txt
python scripts/long-video-reliability.py --duration-seconds 1800 --frame-interval 45 --max-frames 40 --memory-budget-mb 512 --min-free-disk-mb 512 --sample-process-tree --keep-artifacts --output-dir build/visual-resource-1800
```

For 60 and 180 minutes, use 3600/10800 seconds and 90/270-second intervals,
respectively, with separate fresh output directories. Keep the generated
320×180, 1-fps H.264/AAC fixture, 40-frame cap and 3×3 grids unchanged. The
measurement covers generation, probing, extraction and grids; `--media` instead
excludes generation and must be reported separately. Application imports before
the observer starts and cleanup after it stops are outside the interval. No
ASR, OCR, model provider or network call is added by the observer.

Use a dedicated benchmark process with no unrelated child jobs. Do not overlap
local heavy tests when measuring observer overhead. Record source revision,
dependency versions, platform, logical CPU count and the exact command. Results
from one machine or these low-resolution synthetic inputs are not device-wide
or real-course performance guarantees.

## Exact measurement meaning

- The opt-in observer imports only from `scripts/`. The existing application
  `ResourceMonitor` and its parent-only counters are unchanged.
- The root is the current fixture process. New descendants require an observed
  parent-child relationship; PID plus creation time is validated around each
  counter read. A previously observed child remains owned after reparenting,
  only while that same identity survives. Unrelated/reused PIDs are not adopted.
- Each pass sums current RSS readings of observed identities. This is a
  **sequential same-pass sum**, not an atomic instantaneous reading, summed
  individual historical peaks, or unique physical memory. Shared pages count
  once per process. Each sample and the peak's component readings retain their
  time span; maximum collection skew and start-to-start gap are reported.
- CPU adds each identity's own user/system increments from its first reading.
  It never adds `children_user`/`children_system`. Unseen initial/final CPU tails
  and processes that start and exit between discoveries are missing, so the
  result is an observed lower bound. The observer's own sampling CPU is included
  in the root and also reported separately, not subtracted as an exact correction.
- The observer waits 50 ms between passes. Retention is fixed at 128 lifetime
  identities and 256 recent aggregate samples, plus one peak sample. Sample
  detail eviction leaves cumulative totals/peak intact and has an exact counter.
  Identity-cap rejection counts rejected observations, not unique processes.
- Ordinary child exits/read races are expected coverage gaps, with counts and
  missing readings, not fabricated zero counters. Unknown never-observed children
  cannot be counted. The sampler does not kill, wait for or otherwise change the
  lifecycle of media children.
- Access denial, unsupported/bad counters, identity mismatch, observer failure
  or identity-cap loss yields `incomplete`/`unavailable`; missing metrics are null.
  An enabled incomplete/unavailable observer makes the command nonzero after
  saving its report. Media completion is recorded separately. An original media
  exception remains the primary failure if observer shutdown also fails.

## Budget policy and open acceptance

`process_tree_measurement.budget_status` is **not_established**. No sampled RSS,
CPU or elapsed-time result is treated as a budget pass. The existing example
512-MiB parent-RSS ceiling and 512-MiB volume-free-space floor are fixture safety
settings, not a whole-tree RAM limit, CPU budget, disk-write budget or product
SLO. Existing parent counters may be unavailable; this new observer does not
silently reinterpret or strengthen those legacy checks.

Before resource acceptance, a maintainer must specify a device/fixture profile,
the generation-vs-reused-input interval, explicit tree-RSS/CPU/wall/output-space
limits and how incomplete sampling is handled. Limits must not be invented from
a single observed host maximum. Volume free space also reflects unrelated disk
activity; the current fixture does not measure peak artifact space or I/O bytes.

Normal extraction uses bounded FFmpeg batches; fallback and low-resource mode
can still use individual frames. OCR uses important-plus-coverage sampling,
preserves unreviewed metadata, and currently does not choose the summarizer's
vision requests. The historical formula/low-resolution OCR errors and the
remote-call/factual-coverage gap remain open independently of this measurement.

## Measured Linux fixture result, 2026-10-17

Sampler source SHA-256: `25d7d36bc8285671ad92f94b2b4a3ab9599f1182f87bf0c4674a6da56f2a9398`.
The isolated interval was 13:01:53.401–13:03:18.032 UTC, Linux 6.18.55 x86_64,
CPython 3.12.14, nine logical/allowed CPUs, psutil 7.2.2. Both interpreters had
the same `cpython-312-x86_64-linux-gnu` ABI. The test environment reused only the
already-installed psutil package and metadata through a hash-verified narrow
overlay; no host-wide dependency directory was added. No other LearnNote local
aggregate ran during this interval. Two prior setup-only failures, before media
work, were retained separately and excluded from these measurements.

| Generated media duration | Harness wall (s) | Sampled RSS sum peak (MiB) | Observed CPU lower bound (s) | Samples / detail drops |
| --- | ---: | ---: | ---: | ---: |
| 30 minutes | 9.339 | 316.465 | 13.79 | 182 / 0 |
| 60 minutes | 12.959 | 326.125 | 18.11 | 255 / 0 |
| 180 minutes | 40.177 | 355.695 | 56.61 | 787 / 531 |

Every case observed nine process identities (root plus eight descendants), eight
expected exits, no hard errors/identity-cap drops, and zero recorded read races,
ownership races or late samples. Maximum start gaps were 62.593/53.156/56.473 ms;
maximum collection spans were 12.153/3.015/4.620 ms. Peak-reading spans were only
1.411/1.002/0.775 ms, but remain sequential. Zero recorded races does not prove
that no short-lived process escaped discovery.

All cases retained 40 frames and five grids, with four batch extractions and no
single-frame fallback. These extraction counters exclude probing and scene
detection; sampled identities alone are not a complete process-launch audit.
Retained output sizes after completion were 15,484,313 / 30,151,206 / 88,748,374
bytes, including media, frames, grids and reports. These are final sizes, not
peak temporary disk use or bytes written. Existing disk-floor checks passed.

Six alternating off/on pairs reused the same 30-minute input with fresh output
directories. Frame and grid bytes matched in every pair, and the input hash was
unchanged. Whole-command wall medians were 1.793910 s off / 1.734908 s on
(group-median ratio **−3.289%**; median within-pair change **−0.554%**).
Linux waited-family CPU medians were 3.084297 / 3.086330 s (**+0.066%** ratio;
**−0.034%** median paired change). Pair changes ranged −10.509% to +0.913%
wall and −15.517% to +7.636% CPU. This variation supports neither a speedup nor
zero observer cost. Sampling work itself consumed 20.431–31.515 ms CPU in the
enabled reused-input runs; that counter excludes observer import/serialization
and is not its complete overhead.

The outer command includes interpreter/offline-guard startup, report output and
cleanup. Its Linux waited-family CPU is a separate counter with a wider interval
than sampled CPU; do not subtract them to claim an exact missing-tail amount.
These measurements do not calibrate Windows or establish a resource-budget pass.

## Inspected Windows fixture result, 2026-10-17

[Required Reliability run 39036694916](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39036694916)
passed on exact source `a6c23651d8c9723b6c9ecafbfaea2f6d2e0221f0`.
The offline job `117407888349` passed all 20 observer contracts and the existing
media, recovery, range, cancellation and scheduler gates. Its freshness report
confirms the clean source revision. Windows used CPython 3.12.10, four logical
CPUs and psutil 7.2.2; the sampler source hash above is unchanged.

The inspected offline artifact is `12102616487`, with ZIP SHA-256
`1a4ac1af84d90f39c00958c432e62ca7e793b54bd8a2c88e9137f991d486729d`.
Reports are under `long-video-matrix/{1800,3600,10800}-seconds/report.json`.
These generated-input measurements include generation, probing, extraction and
grids. Every case retained 40 frames, reported zero API calls and no
transcription, and had `status=sampled`, zero sampler error counters and
`budget_status=not_established`.

| Media duration (s) | Same-pass RSS peak (bytes / MiB) | Observed own CPU (s) | Sampling CPU (s) | Samples / detail drops | Maximum gap / collection span (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1800 | 231755776 / 221.01953125 | 11.53125 | 1.046875 | 137 / 0 | 0.1409999999999627 / 0.07799999999997453 |
| 3600 | 237531136 / 226.52734375 | 22.234375 | 1.90625 | 263 / 7 | 0.21800000000001774 / 0.1560000000000059 |
| 10800 | 275341312 / 262.5859375 | 65.5625 | 5.578125 | 765 / 509 | 0.20299999999997453 / 0.1409999999999627 |

Independent artifact recomputation verified that each inventory's sum of
`last_cpu_s - baseline_cpu_s` exactly equals its own-CPU aggregate, and each
peak pass's RSS components exactly sum to its reported peak. The 14/15/16
inventoried PID-plus-creation-time identities are unique; all peak identities
belong to those inventories. Zero-read identities were 3/0/1. Detail drops
exactly equal sample counts minus the retained 137/256/256-entry rings.

Observed exits were 13/14/15, disappearances during reads 3/0/0, ownership races
2/1/0, and late samples 2/1/4. These retained coverage gaps do not become complete
observations merely because the command passed. CPU remains a lower bound;
sequential RSS sums can double-count shared pages and miss unsampled peaks.
The 300-second matrix case and standalone 60-minute gate kept sampling disabled.
These Windows results establish neither resource budgets nor cross-device
performance or factual-quality acceptance.

The earlier [8890f79 run 39035890138](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39035890138)
remains failed: a same-tick test subtraction yielded `0.19999999999998863`
against an assertion of `> 0.2`, before the matrix ran. The one-file test-only
correction uses exact controlled timestamps for that positive-gap case and
separately preserves the original same-tick value in a regression. Production
sampler arithmetic, thresholds and workflow were unchanged; the successful run
above supplies the subsequent Windows evidence rather than relabelling that
historical failure.
