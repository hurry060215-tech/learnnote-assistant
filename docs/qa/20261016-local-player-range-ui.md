# Local player range and source identity acceptance

## Scope

The default `web/index.html` reader's actual `desk.js` / `desk-tools.js` player
and range dialog are covered. The legacy `app.js` is intentionally unchanged.
This supplements `local-range-acceptance.py`, which already checks real clipping,
restart recovery, and full-source upgrade without claiming browser acceptance.

The bounded UI changes:

- Bind the local media clock to the task ID, media URL, and current metadata.
  Preserve decimal seconds when filling the range form; never read the previous
  source's position while a new source is loading.
- Delay a citation seek until matching media metadata is ready. Latest seek wins;
  closing or replacing the source cancels pending work. Queued old metadata does
  not consume the new seek, and native player seeking supersedes an older intent.
  Nothing calls `play()` automatically.
- Show source title, current media duration and clip-relative versus original
  range units. Reject non-finite, reversed, negative or out-of-bounds ranges.
- Scope range and full-source requests to the dialog generation, selected task
  and navigation epoch. Duplicate submission cannot create a second task. A late
  reply after Close/navigation cannot reopen the dialog or replace the new note.
- Full-video upgrade retains the existing canonical ancestry traversal and
  explicit confirmation; it never guesses a whole-video URL.

## Hosted browser gate

Run on Windows with installed Microsoft Edge, test Python requirements, and the
existing Playwright dependency:

```
node scripts/local-player-visual-acceptance.cjs build/local-player-ui
```

The helper starts `local-player-fixture.py` in a new application-owned temporary
data directory, applies the existing loopback-only network guard, and generates
20-second, 30fps synthetic H.264/AAC media with exact timed synthetic subtitles. Media,
clipping, task APIs, persistence and playback are real. Only summary generation is
a deterministic fixture. No external model, ASR, real website/account, extension
or native permission prompt is involved. The directory is removed after the run.

The actual UI sends 5.25–15.75 seconds, verifies the 10.5-second clip and its
relative transcript, creates a nested clip, then resolves and upgrades the full
20-second root source. HTTP request bodies are checked against the decimals entered
in rendered fields. The original media/transcript/note hashes remain unchanged.

Delayed real media responses exercise a new 20-second source replacing an already
loaded 5.25-second clip: latest citation seek, Close and source switch. Additional
flows reject an old source's clock during delayed edition navigation, preserve a
new real media seeking-event simulation through delayed transcript rendering, and close/switch during an
accepted range POST whose response has not returned. Duplicate submits are counted.

The report asserts the rendered task ID, current media URL, readyState, exact
currentTime tolerance, duration and paused state. It retains viewport screenshots
at 1440/390 in light/dark for the range form, plus interrupted/source-switch states.
Screenshots require human inspection; geometry checks alone are not visual approval.
The existing `ui-visual.yml` Windows job runs this helper and uploads its directory.

## Local verification and limits

- `node web/tests/local_player.test.mjs`: deterministic metadata, clock and seek
  ordering regression, including old metadata dispatched after source replacement.
- `node web/tests/local_range_ui.test.mjs`: executes production range functions
  with controlled async responses; decimal payload, validation, duplicate, Close,
  same-source revisit, newer navigation and canonical upgrade assertions.
- `node scripts/local-player-visual-acceptance.cjs --self-test`: verifies that the
  report assertions reject wrong source, URL, time, hidden/unloaded media and
  autoplay. It does not launch a browser.
- `python scripts/local-player-fixture.py --data-dir EMPTY_DIR --seed-only`:
  validates actual synthetic fixture creation without opening a socket.

The first hosted run, `38947421130`, used exact head `ba5f96e` and Edge
154.0.4258.62. Cue seeks, decimal current-position controls, invalid bounds,
Escape/Close without submission and four 1440/390 light/dark range screenshots
passed. All four screenshots were inspected: source title, decimal field and
controls are readable and unclipped. The run then correctly failed its 10.5-second
clip duration assertion. The reused long-video fixture had only 1fps; local real
FFmpeg reproduction measured an 11.064026-second container after the requested
5.25–15.75 cut. This was unsuitable for fractional-cut acceptance.

The player-specific fixture now generates 30fps media without changing the shared
long-video fixture or production clipping. Real local probes measure source 20.0,
selected 10.564 and nested 5.330664 seconds, within the unchanged 0.15-second media
container tolerance (requested API bounds remain exact). A real fixture regression
checks these durations before browser acceptance. It also retains a separate 1fps
API baseline: `learning_range` reports requested 5.25–15.75 seconds while
`media_integrity.duration` reports the actual quantized encoded container length
(measured locally as 11.064026 seconds). The saved relative cues remain exactly
0–5.25 / 5.25–10.5 and contain only the requested second and third source segments.
The API therefore exposes requested bounds and measured media length separately;
this is not a promise of exact frame cuts on media that cannot represent those
boundaries. The 30fps tolerance is not widened to accommodate the 1fps limit. Browser reports now retain both
backend and rendered media duration/identity before asserting, plus a failure
viewport/state if later steps fail. The revised hosted gate remains pending. Local Chromium socket binding is unavailable in the editing environment;
no local browser success or visual sign-off is claimed. Native desktop webview,
real course/website behavior, native optional-host permission acceptance, and
provider quality remain outside this gate. The native permission security-warning
boundary is unchanged and must not be bypassed.

The 1fps follow-on also exposed a nested-range defect: encoded padding could be
selected as if it extended the parent’s requested evidence interval. Range
creation now rejects any end beyond the parent’s logical length, without applying
the container’s 0.01-second tolerance to that logical boundary. Real API tests
reject 10.5–11, 0–10.500000001 and 0–10.505 with 422 and no created task. Unit
regressions retain the ordinary full-media container tolerance and legacy
original-offset-only records. The range form caps nested input at 10.5 seconds,
shows the encoded duration separately, and does not copy a playback position from
padding into a valid selection. Hosted acceptance additionally checks that the
nested input rejects padding and retains wide/narrow screenshots of that form.

Logical bounds use serialized decimal arithmetic rather than a numeric tolerance.
The 0.1–0.3 parent accepts a nested end of 0.2, preserves original end 0.3, and
rejects 0.200000001. The UI calculates the same exact decimal max, including
exponent notation, without displaying binary-subtraction noise.


The second hosted run, `38950620700` on `7b5402a`, found a separate lifecycle
defect: the range API correctly encoded 10.56 seconds, but the queued child
preview had already loaded the 20.032-second parent under the child URL. Its
failure screenshot and report retain that mismatch; it was not a timing-tolerance
failure. A range preview now resolves only an atomically completed range artifact
(or a same-range rerun ancestor), returns 409 while unavailable, and uses no-store.
The cheap `range_media_ready` projection allows playback during summarization
once the clip exists, without probing every task on each poll. Full-source reuse
keeps its existing fallback. API regressions compare the actual served bytes with
the selected clip, probe their duration, reject queued/partial media, and verify
both same-range and full-source reruns.

The default player binds metadata to the exact digest/control-generation query,
refreshes an already-open source panel when that task's clip becomes ready, and
does not reopen a closed panel or reset playback for unrelated timestamp updates.
The Edge helper holds real range processing briefly, checks the queued UI and API,
then stays on the same selected task through completion rather than reloading the
page. It still requires a new hosted pass. Programmatic `currentTime` assignments
simulate a manual-position media seeking event; they do not prove physical native
scrub-control interaction. Transcript buttons and range controls are clicked in
the actual UI.

Range-aware metadata lookup is non-probing and never advertises a pending parent
as the child media. Preview, export, rerun, resume, retry and nested-range source
admission verify the completed artifact before consumption. The actual pending
rerun and nested API calls return 409 without creating tasks. Original-source
fallback remains explicit only for internal pending OCR clipping recovery (the
range worker also retains its original input to perform the cut). Legacy finite
offset-only records retain their existing ordinary-media behavior.

The third hosted run, `38954330216` on exact
`1b2a24af5146a347c8a1213683c547425a9e09d9`, verified the repaired queued-to-ready
flow in Edge 154.0.4258.62 without reloading the selected task. The child media
returned 409 while queued, its player had no `src`, and after processing the same
selected child loaded its digest/generation URL with backend duration 10.56 seconds
and actual player duration 10.564 seconds, paused. Requested bounds remained
5.25–15.75 seconds; the nested form showed a logical 10.5-second maximum and
rejected encoded padding. Its four light/dark wide/narrow range screenshots,
queued screenshot and two nested-range screenshots were visually inspected:
source titles, decimal fields, duration distinction and controls were readable
without horizontal clipping.

That run then truthfully failed the unchanged evidence gate: the nested 0–5.25
clip contained only `SYNTHETIC_SECOND`, 16 non-whitespace characters. This is a
fixture prerequisite failure, not a media-identity or timing-tolerance failure.
The [retained report and failure screenshot](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38954330216/artifacts/12069916973)
record `transcript_text` blocking summary generation. The fixture now gives each
unique cue marker a substantive synthetic lesson sentence and the offline fixture
regression processes the actual nested clip through the unchanged evidence gate,
asserting success, exact parent/source bounds, exact cue text and the same 0.15
second media-duration tolerance. No production threshold or helper assertion is
relaxed. Later full-source and delayed seek/navigation checks still require the
next hosted pass.

The fourth run, `38956384233` on `cc150884d0657ba10d5fa1a751dfe309bb10ca72`,
reached full-source upgrade, delayed metadata latest/Close/switch cases, and the
B-source stale-clock rejection. Those retained screenshots were inspected: the
whole source and B show 0:00/0:20, Close removes the source panel, and B's range
dialog visibly rejects A's position. The latest-seek screenshot had scrolled the
player out of view, so subsequent non-dialog snapshots bring a visible player
into the viewport and retain its exact source/revision/time alongside the image.

This run is still failed: an unobserved delayed-edition Playwright callback threw
`Route is already handled!` during route removal. Node exited before the old final
report writer ran; the [artifact retains the screenshots and backend log](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38956384233/artifacts/12071570463),
not a completed acceptance report. The harness now settles held real requests
before unregistering handlers, records unexpected callback rejection, and writes
completed checks/duration samples/screenshots incrementally with `ok:false` until
all checks pass. Only a confirmed `net::ERR_ABORTED` in the deliberate source-switch
case is treated as cancellation; connection failures remain fatal. Deterministic
route tests cover exactly-once release, cancellation, unexpected rejection and
browser teardown. Product behavior, timing bounds and evidence gates are unchanged.
The delayed-transcript and late-range-response cases still need a hosted pass.
