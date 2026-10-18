# Bounded community paging and retained regression evidence

## Accepted paging scope

Product commit `b6d5b53904b52260beab2ff70fb131ad7ee2b105`, followed by the
fixture-only cleanup correction `29c9918e6ec167918151cf278420a39e22764f63`, adds
access to saved opinions beyond the first 500 through bounded pages. The
legacy list/export contract and stored data remain unchanged. Each page has
coherent counts and task/source/revision-bound cursors. Page changes clear
transient question selections and consent; the existing 20-opinion/20,000-
character question budget remains unchanged.

[UI run 39128040320](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39128040320)
main job `117677198024` passed all 42 reports. All 22 paging captures were
inspected, including the 501st item, mobile keyboard focus, stale refresh,
disabled and empty states. Real isolated APIs exercised selection, preview,
deletion, full export, mutation failures, late close/navigation/revocation,
and save/clear without an additional model call. Main artifact `12136907395`
SHA-256: `d92a3993eddf3b239c4eb5955df40b4998c738372d2ed27ad74a4a0b829b4de9`.

One non-paging selection-state `select-light-390.png` frame has an incompletely painted lower
region. It is retained and is not counted as clean visual evidence; adjacent
and later captures render correctly. A paint-timing cause is not established.

The preceding run's held-response failure is retained. Removing an active
Playwright route can continue that request before its held fulfillment settles.
The corrected fixture settles first, then unregisters; a deterministic test
reproduces the old error and verifies cleanup and primary-error preservation.

## Separate failures remain open

The overall UI run failed its reference cancellation/drain criterion: **4.6629
seconds versus the unchanged 2-second limit**. All 80 reference readability
samples passed their original criteria; nearest-rank first-outline p95 values
for 5/30/60/180-minute cohorts were 1.3220/1.3873/1.3681/1.8527 seconds. Maximum
post-transcript visibility acknowledgement was 1.3440 seconds. The separate
joined visual continuation gate passed. Reference artifact `12137341360`
SHA-256: `01fed53cdf093decd9a503230742fe3f364509ae322411f1c555a945ff677e30`.

Server events show repeated cancellation acknowledgements before the final
snapshot observed `callback_finished=true`. There is no independent timestamp
for callback completion and the observer was disabled, so this run does not
identify a lock owner, commit delay or other root cause. A bounded local
reproduction confirms three acknowledgement writes rebuild equivalent FTS
content, but they also change receipt timestamps and event history. Forty
paired 11-row trials found an FTS-only conditional prototype saved approximately
0.56 ms per acknowledgement while retaining transactions and lock acquisition.
This Linux measurement does not explain the Windows delay. No cancellation,
index, cache or storage behavior was changed based on it.

[CI run 39128040312](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39128040312)
also failed `test_real_media_batches_partial_api_cancel_and_source_preservation`:
the immediate partial-note read returned zero visual sections where one was
expected. The original assertion did not retain its reason. The coordinator
publishes synchronously before dispatching another batch, so dispatch order
alone does not establish a cause. The follow-on test retains bounded projection
identity/reason, section kinds, call states and recent event types on failure.
Its assertions, read order, waits and timeouts are unchanged; no content, prompt
or credentials are added to diagnostics.

These are synthetic acceptance results. They do not establish customer podcast
quality, eliminate historical timing variance, close all of issue #158, or
change the immutable v0.2.16 release. No rerun result erases the failures above.

## Follow-on evidence at 715861a

[UI run 39129979224](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39129979224)
passed the main job and all 42 main reports. Independent inspection accepted all
22 paging captures and the diagnostic/native/settings regression evidence. The
previously incomplete 390px selection-state frame renders fully in this run;
its older incomplete image remains retained without a proven cause. Main
artifact `12138255828` SHA-256:
`855ec2043d2eae34c7bb67c2fefd0a008d53fc51f3feb96012ea8892a6c6b5c8`.

The separate reference job again failed cancellation/drain, now **9.0614 seconds
versus 2 seconds**. All 80 readability samples passed: cohort p95 values were
1.8316/2.3353/1.3504/3.3685 seconds and maximum visibility ACK was 2.7970 seconds.
Joined visual continuation passed. Reference artifact `12137148714` SHA-256:
`0a7934b3cb5836f844a40b16a5cfa145051d9725e85f2c14af74e2faaeb56f7e`.
The bounded cancellation diagnostic documents the retained save-to-event span;
no production performance change is established by these observations.

[CI run 39129979242](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/39129979242)
failed earlier in the existing Windows initializer exception-propagation test:
its PowerShell process reached a 15-second timeout with empty output. The script
compiles synthetic types, invokes one initializer and serializes three fields;
it loads no UIA assemblies and opens no app or native dialog. Its follow-on
fixture ceiling is 45 seconds, with one attempt and the original error/result
assertions preserved. This separate managed setup budget does not change native
Save/action deadlines, readback, cancellation or reader visibility limits. The
empty output does not identify the timeout's cause. Windows execution of the
adjustment remains pending; the later scripts suite and projection diagnostic
were never reached in this CI run.
