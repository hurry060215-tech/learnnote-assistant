# One-cancellation boundary diagnostic

This manual diagnostic does not replace or relax the two-second browser gate.
It observes one real loopback HTTP/queue/held-summary cancellation after the
existing seed helper creates 80 retained synthetic caption tasks (11,000 cues,
11,080 evidence rows). It does not launch a browser, reproduce reader-request
concurrency, call model providers or run another 80-row browser matrix.

Run `scripts/progressive-slo-cancel-diagnostic.py --output-dir <new-directory>`.
The directory must not exist. The Reliability workflow exposes the optional
`cancel_diagnostic` boolean, default false, after its existing gates. Only the
new top-level report is uploaded; synthetic data stays in its owned directory.
Dispatch still runs the full normal Reliability offline job before this optional
five-minute step; it does not run the 80-row browser cohort.

The existing opt-in contention observer supplies bounded operation/event rings,
fixed labels, task identity, monotonic wall/thread CPU clocks, lock ownership and
drop counters. Additional fixed wrappers record cancellation handler/request,
worker check, each acknowledgement, manifest save, index return and callback
completion recording. They restore aliases and middleware on exit or setup
failure. No native profiler or shared SQLite/filesystem runtime is patched.
`index_return` includes original best-effort indexing and its commits; it is not
an isolated commit timer. Nested spans are inclusive and must not be summed.

Client cancellation and each drain poll have separate request/response envelopes
in a 64-row ring with a drop count. Callback-completion recording is measured on
the backend clock, independently of the first poll that observes it. The report
includes the signed observation-minus-callback-return interval when its unique
boundary exists. It never infers callback timing from a cancelled status alone.
Failure cleanup independently attempts cancellation, queue stop, HTTP shutdown,
thread join and listener close before restoring aliases. Partial HTTP setup also
owns its acquired socket. Fixed failure flags retain cleanup problems without
replacing an original execution exception, including report-formatting failures.
Joins are bounded: reported live workers make the diagnostic fail, and alias
restoration still occurs on exit. Cleanup failure therefore does not guarantee
that all workers stopped or that aliases stayed installed for their full lifetime.
Observer overhead is included and explicitly unmeasured: there is no matched
observer-off cancellation in this one-cancellation experiment. A fast isolated
result cannot close or explain the browser failure.

## Retained evidence motivating the boundary

The original reports remain unchanged:

- [UI run 39128040320](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39128040320): cancel/drain 4.6628957 seconds.
- [UI run 39129979224](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39129979224): cancel/drain 9.0613939 seconds.

Both observers were disabled. In the latter report, task `51fbd04dcb0d` has final
manifest `updated_at` 13:11:12.611934 UTC and third cancelled `task_updated`
13:11:17.596769 UTC: a 4.984835-second save-to-event span. Source ordering places
that span after `save_task` assigns its timestamp, through atomic manifest
publication/indexing, before `update_task` creates its event. It does not identify
which operation consumed the time. The queue completion timestamp follows the
third event by approximately 2.012 milliseconds.

The earlier report's corresponding final save-to-event span was 0.146877 seconds.
Cancelling-event to queue-completion grows from 3.780002 to 7.540605 seconds; the
second-to-third cancelled-event gap grows from 0.172642 to 5.008466 seconds.
The overlapping selected-task browser GET lasts 3.027792 versus 8.578072 seconds
on the CDP clock. These overlaps are not causal lock or runner attribution.

The cancellation POST and fixture polling use Playwright APIRequestContext,
which is absent from the browser's CDP request trace. Their individual request,
response and polling costs cannot be reconstructed from those retained reports.
The diagnostic records those missing boundaries explicitly, without changing
historical measurements or inferring a clock alignment from SSE delivery.
