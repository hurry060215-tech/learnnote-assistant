# Follow-through verification — 9 October 2026

This record distinguishes executed product behavior from simulated providers,
native platform acceptance and unmeasured quality. Only synthetic data and an
identified public speech fixture were used. No private task, account, credential
or paid model call was used.

## Real local ASR

The unchanged production ASR modules were exercised at product tree
`22b6ddcc38bb4432f0808b728263b366daaa0e9e`, now reachable through merged
[PR #279](https://github.com/hurry060215-tech/learnnote-assistant/pull/279).
The test used the actual local tiny model, VAD, language detection, decoding and
transcription. This is a compatibility check on one English sample, not a general
accuracy, WER or latency benchmark.

| Input and production entry point | Duration | Observed ASR elapsed | Result |
| --- | ---: | ---: | --- |
| Public FLAC through `app.transcriber.transcribe_audio` | 11 s | 2.505958 s | English, meaningful expected phrases, one segment from 0 to 11 s |
| Decoded mono 16 kHz PCM WAV through `app.asr_pipeline.transcribe_extracted_audio` | 11 s | 1.468204 s | Same meaningful transcript; completed progress |
| Three copies of that speech separated by 2 s of silence, through the same pipeline entry | 37 s | 10.468142 s | Three ordered segments: 0–13.21, 13.21–26.42 and 26.42–36.42 s |

Every case returned `source=faster-whisper`, `language=en` and no warning. Segment
times were finite, positive and within the input duration. Transcript text matched
the returned segments; progress was monotonic and ended at the audio duration.
The repository's independent actual WAV decoder check passed with PyAV 18.1.0.

Runtime: Python 3.12.14, faster-whisper 1.2.1, PyAV 18.1.0, CTranslate2 4.8.2,
ONNX Runtime 1.30.0, NumPy 2.5.3, tokenizers 0.23.2 and huggingface-hub 1.31.0.
Inference used CPU/int8 with affinity and numeric thread limits of one, at reduced
process priority. Peak process RSS across the cases was 339,172 KiB, about 331 MiB.
These are single observations under constrained resources.

### Public inputs and reproduction contract

- Model: [Systran/faster-whisper-tiny](https://huggingface.co/Systran/faster-whisper-tiny),
  pinned revision `d90ca5fe260221311c53c58e660288d3deb8d356`.
  `model.bin` is 75,538,270 bytes, SHA-256
  `dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1`.
  The config, tokenizer and vocabulary also matched the official revision's Git
  blob identities. The model is loaded as data by CTranslate2, without repository
  scripts, pickle or `trust_remote_code`.
- Speech: [OpenAI Whisper's JFK FLAC fixture](https://github.com/openai/whisper/blob/6e3be77e1a105e59086e3e21ff5f609fd6fa89a5/tests/jfk.flac),
  1,152,693 bytes, SHA-256
  `63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715`;
  Git blob `e44b7c13897eae7f78beb220c61fe77429a3961d`.
  The fixture comes from the MIT-licensed Whisper repository. The
  [JFK Library](https://www.jfklibrary.org/asset-viewer/archives/jfkwha-001)
  describes the underlying recording as public domain; this does not assert
  byte equivalence to the archive's download.

To repeat the input transformation, decode the FLAC with
`faster_whisper.audio.decode_audio` at its 16 kHz default, clip each float sample
times 32768 to the signed 16-bit range, and write little-endian mono PCM WAV.
For the third case concatenate speech, 32,000 zero samples, speech, another
32,000 zero samples, and speech. Pass an explicit local model directory to
`transcribe_audio`; for the pipeline route use `TaskOptions` with
`transcriber="faster-whisper"`, that directory as `whisper_model`, an empty
`llm_api_key` and `use_saved_connection=False`. Capture the supplied progress
callback and apply the assertions described above.

Run only after independently obtaining and verifying the public files. The
verification did not download models during inference. It started with an empty
environment, fresh isolated data/cache/temp directories, blank provider keys,
HF/Transformers offline flags and native telemetry opt-outs. Imports and calls
ran inside the repository's `offline_network()` guard, with an additional Python
audit hook rejecting networking, credential-file reads and unrelated workspace
access. A deliberate DNS sentinel was rejected before transport.

The native runtime logged a denied UCX local VFS socket operation, while inference
completed. Python guards do not cover every native system call. No packet capture
or OS network namespace was used; this is not a kernel-level network attestation.
Long-audio chunking over 600 s, cancellation, queue endurance, GPU, other models,
multilingual quality and summary quality are outside this check.

### Real queue and resource-report follow-through

The existing `scripts/queue-asr-reliability.py` was then run against the stage
timing integration tree `28273d84963cfda19aea8bdeb5d66435ae0fa0ec`, using the same
verified public speech and local tiny model. FFmpeg, decoding, local ASR, durable
queue admission and task storage were real. The summary function was explicitly
replaced by the script's deterministic reference adapter.

Five synthetic jobs were submitted. Three completed actual local ASR, one used
the declared subtitle fixture, and the fifth was cancelled while queued in
0.0023 s. Peak execution was one heavy and one light lane. All four completed
tasks had a note and resource report; durable states were four `done` and one
`cancelled`. Their queue intervals and completed attempt records were checked.
The run took 11.155 s, with 186 resource samples and peak process RSS of
384,794,624 bytes. This establishes queued cancellation and short-task dispatch,
not interruption of an in-flight model request or long-video performance.

A separate run of the repaired `scripts/benchmark-public-media-asr.py` used the
11-second public PCM WAV. Actual ASR passed in 2.032 s, with two complete resource
samples, peak process RSS of 298,078,208 bytes and interval CPU mean 93.47% on the
constrained single CPU. The input WAV was 352,044 bytes, SHA-256
`b9e1ae4e0837e7b99f05e4f61f70f5732320a56614ab4514d803fa85f9a563c4`.
The report saved aggregate measurements, not transcript text. Missing metrics, short runs and unavailable platform APIs are covered by
deterministic tests; they remain distinct from an actual measured zero. See
[resource-report semantics](../PUBLIC_MEDIA_ASR_BENCHMARK.md) and issue #281.
The same offline guard, blank environment, local asset hashes and audit
restrictions applied. Native UCX again logged a denied local VFS socket operation.

## Progressive side panel and recorded progress

[PR #279](https://github.com/hurry060215-tech/learnnote-assistant/pull/279) passed
1,075 offline backend tests and all six final PR workflow groups. Its shipped
side-panel assets ran in actual Edge 153.0.4234.48 against synthetic HTTP,
EventSource and Chrome API fixtures. DOM selection, scroll preservation and
320 px layout were checked. This is not native extension permission acceptance.

A separate real loopback HTTP/SSE check connected the production task, note and
event routes to the shipped side-panel controller: 23 requests, two streams and
17 SSE frames passed. It covered initial outline, partial arrival, stable outline
nodes, failure, retry after historical failure, original transcript preservation,
byte-preserving draft backup and cancellation stopping further reads. Its DOM was
a test implementation, so it adds wire-level evidence rather than browser pixels.

[PR #280](https://github.com/hurry060215-tech/learnnote-assistant/pull/280) passed
236 Node test entries across 48 web and 69 extension files. The full script and
desktop discovery ran 204 tests: 200 passed, four platform skips. Actual Edge
checked 16 combinations of two dialogs, two themes and independent motion/
transparency preferences, including the normal setting. Reader DOM checks
distinguished a 23-second download from one-second media preparation and left
unrecorded historical download duration unknown. All four final PR and all four
triggered main workflows passed; detailed CodeQL reported zero new alerts.

The latest verified main at that point was
`f85e5035d44e8a5937a3031557d336fc303b284b`, with container digest
`sha256:5b91f626b75b5ac2da5e1919669beeb1c199cad4ee6278ab20805435f3d0d459`.
Both amd64 and arm64 images ran the actual synthetic WAV decoder check using
PyAV 18.1.0 without a model download.

The current screenshots for these two PRs were not manually inspected. Automated
DOM/computed-style assertions and workflow logs are verified; a successful UI
workflow is not a claim of a completed human pixel review.

## Resource-report and multi-cue fixes on main

[PR #283](https://github.com/hurry060215-tech/learnnote-assistant/pull/283) fixes
[#281](https://github.com/hurry060215-tech/learnnote-assistant/issues/281): the
Windows-only benchmark sampler previously failed on Linux while reporting
invented zero resource values. Missing observations now stay null, and resource
status is distinct from transcription success. The exact 1,120-test backend
suite, 218 script/desktop checks (four existing skips), six PR workflows and
five triggered main workflows passed. Detailed CodeQL reported no new alerts.
Main `03337c9f5fddc1f6db63cd7495e5381c96596520` produced image
`sha256:890f991be9e6a50314fa45df0c5367d8752f902f22909501e878fc2a5517750b`;
both architectures performed actual WAV decoding without a model download.

[PR #284](https://github.com/hurry060215-tech/learnnote-assistant/pull/284) adds
explicit adjacent-cue subtitle intervals to personal annotations. Every cue's
identity, original bounds and full-content hash are retained. Modified endpoints
are rejected instead of silently narrowing a requested interval. Regeneration
resolves only a complete, intact and unique sequence; the original personal
record remains unchanged until an explicit save. Stale picker responses cannot
replace a newer selection, and saving waits for interval validation.

The exact integrated tree passed 1,131 backend tests, 246 Node entries and
218 script/desktop checks (four existing skips). All seven PR workflow groups
passed, including 22 plugin tests, TypeScript/build and real Edge 153.0.4234.48
connected to the actual local backend. The extended browser fixture saved,
invalidated and repaired a multi-cue interval and rejected altered boundaries.
Detailed CodeQL had no new alerts and there were no unresolved review threads.
The CI merge tree matched the local tree. Current screenshots were not manually
inspected; native Obsidian and real-vault synchronization remain unverified.

All seven main workflow groups also passed at
`1ede8b09e259033872dc285d1c17a67671ecd7dc`, producing image
`sha256:53a2fbbf74b2b5a50c3d365ced00c4340286d49cee776c1b1c7b5dd6dd0177b9`.
Both architectures executed the actual WAV decoder check. Issue #140 remains
open for its remaining native-host and broader acceptance boundaries.

## Attempt-bound stage timings

[PR #282](https://github.com/hurry060215-tech/learnnote-assistant/pull/282)
completed the measured queue, frame/local-OCR, vision-batch, merge and local-check
intervals. Historical missing observations stay unknown, unused detailed stages
stay skipped, and overlapping aggregate/detail rows are explicitly labeled.
These local checks are not semantic factual verification.

Late callbacks cannot write to or finish a newer retry. Timing writes share the
existing storage lock; an optional observer failure cannot change provider
requests, retry a request, hide a pipeline error or fail an already published
note. Caption-only routes finish their attempt after successful artifact/state
writes. The exact backend tree passed 1,120 guarded tests, with 65 additional
focused caption/mode/provenance checks. Provider, repair and token-call ASTs were
compared with the baseline. Actual Edge exercised the duration rows and warning.

All six final PR and six triggered main workflow groups passed. Main
`6279fca6c049d92dc1be2ef2af37c44c1c720bb9` produced image
`sha256:62bb134758569ef8f3317b5742ae5c8ad66f262917960baa890d0ee8d94078cb`;
both architectures executed the actual WAV decoder check. The CI merge tree
matched the locally verified tree. Dynamic ETA and broader performance/semantic
acceptance remain open.

## Bounded classic task-list extraction

[PR #285](https://github.com/hurry060215-tech/learnnote-assistant/pull/285)
extracts fourteen pure task-list functions into a 207-line module. Five adapters
continue reading current selection, filters, history and clock at each call.
The existing UI, labels, stable ordering, API, persisted data and exports stay
compatible with 143 pre-extraction output snapshots. App shrinks by 151 lines
from 9,603 to 9,452; the enforced cap drops to 9,455. The full four-file task
module group is 10,054 lines under a 10,100-line cap, including 56 lines of
extraction overhead. This is partial architecture progress, not a net bundle
reduction or completion of issue #143.

The combined tree passed 1,131 guarded backend tests, 247 Node entries across
49 web and 69 extension files, and 222 script/desktop tests (four existing skips).
An earlier backend execution was interrupted without a terminal result; the
fresh isolated 103.967-second rerun supplied the passing result. All five final
PR workflows passed, with zero new CodeQL alerts and no unresolved review
threads. Actual Edge classic/desk workflows and CI packaging smoke passed.
The CI merge tree exactly matched the locally verified product tree.

Main `41eaa32c6157539b0e0db6e61dc5276f4b935402` produced image
`sha256:41fd3b2371965c468dbff4864d86173963f48ce7ff59e6d3349fcab291a6ce7b`
in [Container run 37979216954](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37979216954).
Both amd64 and arm64 actually decoded the synthetic WAV with PyAV 18.1.0 and
no model download. Its main
[CI](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37979216986),
[UI](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37979216960),
[CodeQL](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37979216927)
and [platform contracts](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37979216918)
are separate from the exact-head PR evidence above. Manual inspection of the
new screenshot, native extension acceptance and long-task recovery are not
inferred from these automated checks.

## Bounded SSE endurance attempt: interrupted, not a two-hour pass

The real loopback HTTP/SSE run began at 15:58:57.294378 UTC and was scheduled
through 17:58:57.294378 UTC. It used the production event router and task/event
storage at main `0bb7a1b0514ffc787d7e1289f97d0089e6c165d9`, product tree
`57b8283ab7c9800937c07f0d5621388c0687293d`, with a synthetic task, no model
calls and the repository's offline network guard. This was a minimal server,
not the full application lifecycle or a native extension test.

The run was interrupted before its terminal checks. At the 18:23–18:25 UTC
inspection, its execution session was unavailable and no soak/server process
remained. The original report's `running` value is a stale checkpoint; it is
not evidence of an active process or success. No exception or terminal report
was recorded, so the interruption's cause is unconfirmed.

- The last durable client checkpoint was 6,936.089 seconds (115.6 minutes):
  6,791 consecutively numbered events, 453 connections, 452 planned disconnects,
  seven clean server restarts, and one observed heartbeat.
- Disk inspection found 6,847 valid event records, including two initial events
  and synthetic sequence 1 through 6,845 without gaps. The last persisted event
  was at 17:55:27.179124 UTC, about 116.5 minutes after the start.
- Delivery of the 56 events persisted after the last client checkpoint is
  unconfirmed. This does not establish that those events were lost.
- A terminal event and the final complete stream-to-disk comparison were never
  recorded. The requested 7,200-second run therefore **did not pass**. The
  synthetic task was left unchanged; no successful state was manufactured.

The original report and logs were preserved. The separate
[interruption assessment](20261009-event-soak-assessment.json) records the
observed counts, timing and source-file hashes without rewriting the original
checkpoint. The exact [bounded harness](20261009-event-soak.py) is included for
review. Its recorded SHA-256 is
`c943697b090ee6cd273ff2248425608b1f671a7b43b1e0c5467af8da59310b41`.
It asserts its historical product tree deliberately; reproducing that run
requires a checkout of the recorded commit and a fresh output directory.
No automatic extension or full two-hour rerun was performed.

The earlier 8.517-second smoke reached terminal success with 82 events,
12 connections and two clean restarts. It verifies the harness's short terminal
path only and cannot substitute for the interrupted endurance run. Likewise,
clean restarts do not establish abrupt-crash recovery or provider cancellation.

## Native browser permission acceptance still outstanding

Issue #135 remains open. The next proposed environment is a disposable Windows
CI session with installed Chrome and Edge, each using a fresh temporary profile.
No user profile, login or store account is needed. Enabling Developer mode,
loading the exact extension and interacting with real permission dialogs are
separate pending acceptance actions, not part of the already executed DOM tests.

The current extension declares `activeTab`, `tabs`, `scripting`, `webRequest`,
`webNavigation`, `cookies`, `storage`, `alarms`, `sidePanel` and `downloads`, with
required localhost/127.0.0.1 backend access and optional site hosts. The proposed
test would grant only a synthetic `http://127.0.0.2/*` lesson origin and use a
second ungranted `http://127.0.0.3/*` origin. Dummy cookie/evidence recipients
would stay on the same runner's local backend.

Required observations are real first-time approval and denial in separate fresh
profiles; native revocation and `permissions.onRemoved`; candidate-cache cleanup;
closing or leaving the old tab before testing revoked access; restart persistence;
and reauthorization. A legitimately retained permission must not be misreported
as a new consent dialog. Record exact browser and extension versions, manifest
hash, full native-window evidence and the selected UI controls. No profile edits,
autogrants, registry security changes or mocked permission APIs can replace this
matrix. If the environment cannot operate the real dialog, record a blocker.
