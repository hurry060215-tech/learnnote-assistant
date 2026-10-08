# Progressive reference outline and evidence-write budget

Refs #148 and #151. These epics remain open for model-generated incremental
topic chapters, separate vision/merge/verification timings and richer route
estimates. This change does not call source excerpts an AI summary.

## Reader and source contract

Complete timed captions now produce a time-range reading outline alongside
the original short excerpt preview. Five-minute groups cover the full source,
including the tail of a three-hour transcript. IDs are based on stable source
time buckets. `draft_sections.json` explicitly records `status=draft`,
`summary_generated=false`, `verified=false`, source cue indexes and ranges.
Appending cues preserves completed earlier buckets. Untimed text does not
invent chapter times. The final claim gate and generated-note path are intact.

The desk no longer rebuilds an unchanged edition on every progress event.
When its text changes, it preserves the visible source heading/scroll offset.
The updated view still uses the existing sanitized Markdown renderer.

## Concrete performance repair

The local library previously removed all task evidence and reopened/committed
SQLite once for every caption cue on each progress update. An unindexed FTS
delete also scanned the growing corpus repeatedly. Task evidence is now
replaced in one transaction, with one connection and one bulk deletion before
insertion. The same preparation/storage fields are used by single inserts and
batches. Tests prove source-text parity, one connection for360 cues, rollback
on a mid-batch failure, search-index consistency and other-task isolation.

## Repeatable reference SLO

`python scripts/progressive-slo.py --repetitions 20 --output-dir <new-directory>`
submits real local queue tasks with complete synthetic platform captions for
5/30/60/180 minutes. The final summary uses a declared deterministic reference
adapter. Before that adapter runs, the normal reader artifact must contain the
time-based outline and its final source range. The test records nearest-rank
p95 from task creation to readable outline (budget10 seconds), and from the
transcript-complete event to draft-ready (budget5 seconds). No ASR, video
download, provider call, queue contention or generated-summary-quality claim
is part of this reference. Native telemetry is disabled before imports and the
existing offline guard rejects external transport.

Cloud results on2026-10-08,20 samples per duration:

| Duration | Before atomic evidence batch | After batch | After transcript |
| --- | ---: | ---: | ---: |
|5 min|0.0926 s|0.0574 s|0.0153 s|
|30 min|0.3348 s|0.1426 s|0.0233 s|
|60 min|1.1592 s|0.1605 s|0.0186 s|
|180 min|7.1824 s|0.3134 s|0.0291 s|

The reliability workflow and clean-commit release suite now execute all80
reference runs and archive the report. Actual CI p95 values may differ from
this cloud machine. The gate fails when its reference budget is exceeded.
These results are neither whole-video completion timings nor a promise about
third-party network/model latency. A readable temporal outline also does not
satisfy the still-open requirement for progressively generated topic chapters.
