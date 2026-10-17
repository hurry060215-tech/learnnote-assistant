# Reference-fixture contention diagnostics

Date: 2026-10-17. Collector implementation: `b67f8c5d76a0ea888fa4863539018030409f9212`.
Snapshot consistency follow-on: `0b8c62404d1f487ff18ef9caad46777c85fbc63a`.

## Open question

In [run 39021819029](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39021819029)
at `ab796ab241718d8dc4236bc4a8cda3ff33b2304a`, reference sample 74
(180 minutes, repetition 14, task `9d7e4e59db4a`) had a 9.887-second selected-task
GET while a full-list GET overlapped it. Backend events separated draft readiness
from the summarizing update by 10.458 seconds. The complete artifact is
[12097341904](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39021819029/artifacts/12097341904).

This local investigation did **not** establish the Windows lock owner or reproduce
the approximately ten-second stall. Linux state-lease entries and a cold duration
history scan were only milliseconds. That does not rule them out on Windows.
The mixed-generation transcript artifact race remains a separate open issue.

## Opt-in scope and bounds

Only the owned synthetic reference fixture loads the observer, after validating
its data marker and receiving the explicit `--contention-diagnostics` flag.
Production startup never imports it. There are no global Path, open, JSON,
SQLite or threading patches.

Explicit, restored wrappers observe the existing task RLock and its four aliases,
state-lease entry, HTTP/handler/update boundaries, task projection, history reads,
atomic writes and library indexing. They preserve the underlying lock, acquisition
arguments/timeouts, reentrancy, results and exceptions. Partial installation also
restores its changes. No cache, lock policy or product behavior is changed.

The collector retains at most:

- 256 recent completed operations and 128 active operations
- 256 recent slow events and 64 longest slow events reserved by kind (see follow-on below)
- 32 metric keys per aggregate

Overflow counts are included. Source text, paths, configuration values and stack
dumps are excluded. Snapshot JSON is captured before the owned backend restart
and during final cleanup, outside the sample timing windows. Existing artifact
upload rules include these top-level JSON files. Optional diagnostic capture
failure does not replace the original acceptance failure.

## Reading the measurements

- `owner_at_entry` is a point-in-time snapshot, not complete attribution across
  successive owners. Slow-hold intervals provide only bounded correlation.
- Hold time ends immediately before the underlying release call; that call and
  post-release observer recording are excluded.
- Nested spans are inclusive and must not be added as disjoint costs.
- I/O-bearing function boundaries include decoding and validation. They are not
  pure OS I/O measurements. Synchronous wall and thread CPU are separate; HTTP
  envelope CPU is omitted.
- No current consumer uses Condition's private release/restore methods on this
  task lock. The queue's Condition owns a separate RLock.

## Local overhead and preservation checks

Two six-pair alternating disabled/enabled experiments retained all original 80
completed tasks: 20 each at 5, 30, 60 and 180 minutes, with full captions. Complete
response equality passed after normalizing only observation clocks and relocated
fixture roots; the original 80 file inventories remained unchanged. A separate
81st task exercised real running/update/cancel behavior without dropping a task.

On Linux/Python 3.12.14, median list wall/thread CPU was 0.639/0.639 seconds disabled
versus 0.739/0.739 enabled in the first experiment, and 0.679/0.679 versus
0.719/0.719 in the second experiment. The observed list difference was **5.9–15.6%**
(about 40–100 ms). These noisy local experiments do not establish Windows overhead
or a product speedup. The hosted report explicitly marks enabled timings as
including diagnostic overhead, not clean production latency.

After the snapshot consistency fix, a third six-pair experiment measured
0.575/0.575 seconds disabled versus 0.698/0.698 enabled: approximately 123 ms,
**21.4%**. The earlier 5.9–15.6% range therefore describes the first two experiments,
not an upper bound on observer overhead. All three results are retained; no
claim about the small fix causing the variation is established. Selected GET
medians in the third experiment were 8.75 ms disabled and 8.99 ms enabled.

The follow-on serializes active-row finalization with the collector's existing
metadata mutex. A deterministic regression reproduces the original concurrent
snapshot dictionary-resize failure and verifies coherent snapshots after the fix.
It introduces no product lock or global synchronization change.

Focused contracts cover ownership/waiter correlation, native lock behavior,
bounds, privacy, restoration, opt-in isolation, real HTTP reader freshness and
primary-failure preservation. Original admission/SSE/cancel/retry/restart tests
also pass. The first hosted Windows owner/I/O evidence is described below.

## Fixed-kind retention follow-on

[Run 39024419361](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39024419361)
at `2215f8e79912d29c09679555e5bb43b899bc0bdf` captured Windows evidence with the
original global 64-event retention policy. Its 64 longest events were all
handler/list/projection boundaries above 1.331655 seconds, so the longest
1.304-second lock wait and 1.301-second hold lost their individual owner records.
Their operation aggregates survived. Sample 72 separately retained a direct
195.806 ms overlap between a selected-reader wait and an update-owned task-lock
hold containing library indexing. This does not explain the earlier ten-second
stall. The run stopped on sample 72's detached-heading assertion before completing
the 80-sample matrix or reference lifecycle.

Collector follow-on `68f1cbbdee929766a37edddbd23b710738d5c5f6` keeps the same total
64-event cap, partitioned into 16 lock waits, 16 lock holds, 8 lease entries and
24 other boundaries. Per-kind limits and dropped counts are explicit; the
existing cumulative drop count remains. The smaller supported test capacities
use deterministic proportional allocation without exceeding their total cap.
This protects each kind's longest events but does not guarantee every successive
owner, paired event or I/O span survives.

A fourth six-pair Linux experiment on these collector bytes measured list median
wall time 0.586945 seconds disabled versus 0.696528 enabled, **18.67% overhead**;
thread CPU was 0.586761 versus 0.696478 seconds, **18.70%**. Selected GET medians
were 8.55 and 8.79 ms. Full response equality and original 80 file preservation
passed. All earlier overhead results remain evidence; this experiment does not
establish an improvement or Windows overhead. All 25 focused contracts and all
394 scripts tests pass (3 skipped). Instrumented hosted timings remain diagnostic.

## Exit criterion

Keep all 80 samples, original timing clocks, thresholds and failure predicates
unchanged during diagnosis. After the bounded diagnostic run,
remove `--contention-diagnostics` from the workflow invocation and rerun the
original complete gate with the observer disabled. An instrumented diagnostic
run alone is not a clean performance acceptance result.


## Return to the clean required gate

Run [39026365346](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39026365346)
on `2e91eb6a069a7785d2ab1fe680edb7595d1cbedb` completed all 80 reference
rows and reference cancellation/recovery with the collector enabled. These
remain instrumented results. The independent joined visual scenario later
failed its stage viewport assertion; that failure is retained separately.

The required workflow now removes only `--contention-diagnostics`. It retains
the original full dataset, clocks, thresholds, lifecycle checks and fatal
failures. The opt-in fixture collector remains available for a separate
diagnostic investigation. A clean hosted run is still pending.

The diagnostic run directly correlated a 4.329-second completion-owned task
lock with a selected-reader wait after sample 60's readable acknowledgement.
Library indexing occupied 99.883% of that hold, but the boundary includes
artifact reads, library locking and catalog/evidence writes. This is an open
performance finding, not proof that one specific I/O operation is responsible.
No production lock or indexing behavior is changed by retiring the observer.
