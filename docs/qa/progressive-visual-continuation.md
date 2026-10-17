# Joined visual continuation acceptance

This gate exercises the real local-media pipeline and current Edge reader with
owned synthetic inputs. It complements the separate 80-sample complete-caption
reference SLO; it does not change that matrix, its clocks, or its thresholds.

## Boundary

The fixture generates two 36-second, 320 × 180, 2 fps audio/video files with FFmpeg
and complete embedded SRT captions. The second input changes the caption bytes.
Both are uploaded through `/api/tasks/from-local`. Production admission, queue,
embedded-caption extraction, transcript preparation, frame/grid extraction,
vision batch scheduling, cache writes, partial callbacks, persisted projections,
HTTP APIs, native task SSE, and reader rendering remain active.

Only `openai.resources.chat.completions.Completions.create` is substituted. It
receives the actual generated image payload and prompt, binds them to the owned
task and generation, and returns explicitly unverified deterministic draft prose
when that batch is released. It never contacts a provider. Unexpected download,
ASR, merge completion, or external network attempts fail and are recorded. The
owned fixture disables automatic update checks before application startup; the
forced-update denial remains a separate regression.

This is evidence for pipeline and reading continuity, not model quality, semantic
verification, provider latency, or a successful final note. The real cache is
written and its hashes are retained; this scenario does not test cache-hit replay
in a new process. It does not exercise the positive #129 verification transition
or remove a Draft label.

## Joined observations

1. Real captions become a source-bound temporal draft while actual visual
   completions 1 and 2 are held. Resolve the exact first literal caption excerpt
   inside its source-bound temporal section, scroll it once, and require visible,
   unobscured bounds before the caption screenshot.
2. Release batch 2 first. Match its native SSE request/task/event ID and bounded
   section identity to the persisted document revision, current combined
   `/partial-note` revision, attempt, source, generation, and rendered batch ID.
3. Select the exact first deterministic paragraph directly inside batch 2's
   Markdown body. The warning badge and source buttons are not prose anchors.
   Release batch 1 while later real batches remain held. The existing chapter, batch, paragraph, selection anchor/focus nodes and
   offsets and direct body membership must survive insertion. The report retains
   the actual bounded paragraph text before and after insertion. The paragraph
   stays visible and unobscured,
   within 2 CSS pixels of its original viewport position. No corrective reading
   scroll is performed during that comparison.
4. Cancel while later completion workers are held. Require both the real queue
   callback and every deterministic completion worker to drain within 2 seconds.
   Preserve source, captions, draft, partial note, frame/grid and cache hashes.
   The reader must show a stopped state, with the unverified content still readable.
5. Separately scroll to real stage rows and the task-owned source grid. The
   visible terminal timeline must show completed frames, stopped vision, and
   pending merge/verification. These are actual stage states, not a new timing
   performance claim. After the retained-prose capture, resolve the current open
   timeline and perform its one explicit scroll synchronously, bound to the
   route, reader source/revision and selected task generation from the existing
   selection/metadata events. Record before/after node identity and scroll; a
   later strict observation immediately before the PNG does not scroll again.
   Capture the retained visual draft at 390 px as well.
6. Upload the changed source. Hold a genuinely fetched old-source partial response,
   navigate to the new task, and then deliver the unchanged old response. It must
   not replace the current reader or introduce old batches. Original artifact
   hashes stay unchanged. Separately resolve and show the exact changed caption
   after delivering that old response, retaining current task and section identity
   in its viewport evidence and screenshot. Cancel and drain the changed-source
   task too.

The delayed response is an actual production HTTP response, not fabricated JSON.
The native SSE observer retains its strict same-origin task-stream/request-ID
binding. The helper does not reload the page to hide navigation failures.

## Running

Prerequisites: the repository's constrained backend test dependencies, Node and
Playwright, an installed native Microsoft Edge executable, and installed FFmpeg
and FFprobe on PATH. The acceptance helper performs no browser, model, media, or FFmpeg download.
The hosted workflow separately provisions Chocolatey `ffmpeg` version `8.1.0`,
checks both FFmpeg and FFprobe version output, and retains `media-tools.json`.
This pinned package uses Gyan static essentials builds, a Windows build source
linked by [FFmpeg's official download page](https://ffmpeg.org/download.html).
The [package's published verification](https://community.chocolatey.org/packages/ffmpeg/8.1.0)
records the included archive SHA256
`9B299A21FC1CA36AC22E4911F8958404C228E4059583C4651743122A8D0A7E56`.
Package installation failure or either missing/wrong-version binary fails the
required gate; no alternate binary source or checksum bypass is used.
Set `LEARNNOTE_ACCEPTANCE_PYTHON` to the prepared Python interpreter, then run:

```sh
node scripts/progressive-visual-api-acceptance.cjs build/progressive-visual-ui
```

A configured browser override must resolve to an existing canonical Edge
executable; missing or non-Edge overrides fail. The report records the owned
launch path, browser version, user agent, and brands. The executable is launch
provenance, not independently observed command-line telemetry. Headless user
agent spelling alone is not used to infer browser identity.

Focused local contracts:

```sh
python -m unittest scripts.tests.test_progressive_visual_fixture -v
node web/tests/progressive_visual_fixture.test.mjs
```

The Python contracts run actual FFmpeg preparation and real HTTP/queue lifecycle,
including an actual SSE frame through the JavaScript identity join. Browser-free
Node contracts reject wrong identities, hidden or replaced prose, changed
selection, offscreen geometry, false terminal stage states, and unrelated cleanup
targets. The regression includes an outer-div warning-badge decoy and missing,
duplicated,
wrong-source, moved-body, obscured and offscreen content. Caption placement occurs
before the retained-prose comparison or after changed-source response delivery;
it does not re-scroll during insertion or alter the separate 80-row SLO clocks.
An actual `renderStatus` regression reproduces a timeline handle becoming
detached when the status panel repaints. The stage-navigation fixture resolves
its current target inside the scroll call and rejects wrong source/generation
or a closed/detached panel. It does not add product autoscroll or repeatedly seek
a passing viewport. The earlier hosted offscreen-stage failure did not record
target identity, so this reproduction does not establish its exact cause.
Hosted native Edge and screenshot inspection remain required before
claiming this browser scenario passed.

## Artifacts and cleanup

The output directory contains `report.json`, at most 1 MiB of `backend.log`, and
up to eight successful screenshots: caption draft, batch 2, earlier-batch
insertion, cancelled retained visual draft, actual stage states, source grid,
390 px retained draft, and changed-source stale-response rejection. On failure,
`failure.png` and bounded page/task/fixture diagnostics are best-effort evidence.
Errors and external-request records retain at most 64 entries with dropped
counts; native SSE and network records reuse the existing bounded observer.
Each fixture task snapshot retains at most 256 stored events. Forbidden attempts
retain the first 64 entries and an exact total count.
After a browser failure, the owned fixture also returns at most 32 current Python
thread stacks with 32 code locations each and explicit truncation indicators.
Only repository-relative filenames (otherwise basenames), function names and
line numbers are retained; no frame locals, source lines, arguments or environment
values are read. This is a failure-only observation before cleanup, outside the
successful reading/cancellation measurements. It can distinguish a worker waiting
inside normalization, transcript preparation or a completion; it does not by
itself identify a native FFmpeg child wait or prove a suspected pipe interaction.

Startup emits a fixed sequence of phase names to stderr, with the owned PID and
monotonic timestamp. A one-shot all-thread stack dump at 20 seconds helps locate
an import or preparation stall before the existing 45-second API-test and
60-second browser startup deadlines. It is cancelled when server setup is ready
or fails. These diagnostics contain code locations, not environment variables,
request payloads or model credentials. The Windows startup timeout observed in
run 39014763339 had no phase/stack evidence, so its blocking cause remains
unresolved; missing FFprobe is a separately confirmed provisioning gap.

Run 39016337309 subsequently captured the main thread importing NumPy through
the optional ONNX Runtime offline-guard initialization while the control thread
was reading piped stdin. This matches the Windows subprocess/reader/import
pattern and stack in [NumPy issue 24290](https://github.com/numpy/numpy/issues/24290);
it is a stack match, not a local reproduction of the Windows native deadlock.
The fixture now completes offline-guard and application imports before starting
its stdin reader, and starts that reader before any media generation. Tests
check the actual named reader thread at those boundaries and send a real stdin
shutdown during generation, requiring the owned child to be reaped. The hosted
Windows rerun remains necessary to establish that this resolves its startup.

The fixture owns a fresh temporary data directory and all launched processes.
Cleanup first sends an explicit stdin shutdown request. During media generation,
the production cancellable subprocess helper kills and reaps its owned command;
during processing, shutdown requests task cancellation. If the process does not
exit within the bounded grace period, the harness verifies its exact owned launch
and terminates only that process tree (Windows PID tree or owned POSIX process
group). Regression tests start actual child processes and verify cooperative and
fallback teardown, plus cancellation of a running generation command. This
emergency cleanup is separate from the measured normal task cancellation/drain.
Report, browser, and backend cleanup are attempted independently, preserving the
primary failure. The helper does not kill processes by executable name or erase
user data.
