# Issue #139: playback, claim markers and note blocks

This change completes the remaining reader-side synchronization path on top of
PR #246's transcript/frame source panel. It does not change stored claim maps,
source identities, user editions, evidence classification or playback storage.

## Reader behavior

- The reader consumes the saved v6 claim map only when its task ID, note SHA-256
  revision, Unicode-codepoint spans, exact source text and evidence references
  are consistent. Missing/old/ambiguous maps visibly disable synchronization.
- The Markdown renderer optionally exposes original source offsets on prose
  paragraphs and list items. Claim markers attach to exactly one enclosing
  source block. Identical text in another paragraph, a heading or code is never
  used as a substitute. Highlighting is at the paragraph/list-item level.
- Local player time updates highlight every associated note marker and display
  its sources in the same source panel as the subtitle and frame tracks.
  Disjoint evidence intervals remain separate. Gaps clear the highlights.
  Candidate intervals do not extend a directly supported claim's coverage.
- Note scrolling is an unchecked, explicit control separate from subtitle
  following. It never focuses a node, interrupts a text selection or scrolls a
  focused note control. Source buttons under keyboard focus remain in place
  while playback continues; the list resumes following when focus leaves it.
- Claim markers, the task-status source list, card/mistake evidence, and question
  citations use the same canonical source-opening path. Source IDs must resolve
  uniquely. No title, URL or fuzzy text matching is used. Old lookup successes,
  failures, close actions and navigation round trips cannot overtake a newer
  navigation. Same-source clicks preserve the rendered note and keyboard focus.
- Editing removes markers immediately. Saving an edited revision refuses the
  old map. A missing note block is disclosed instead of guessing its position.
- Subtitle-only sources retain claim clicks and exact subtitle positioning with
  the player hidden. Existing safe original-page/extension routes are unchanged.
- “Only located”, inference and candidate evidence remain visibly reviewable.
  A direct source match is not a claim of external factual verification.

The long transcript window and its keyboard behavior are retained. This module
only reads a claim map; it does not write playback position or viewing history.
The runtime CSS guard receives an explicit 20-line allowance (2250 → 2270).
Against main `5eaaab4`, the declared runtime stylesheet total changes from 2249
to 2262 lines: 13 added lines, including the section comment and spacing. No
unrelated CSS was compressed and no other guard changed. Existing checkbox,
focus, time-link pill and source-target highlight styles are reused. The added
rules supply the bounded, scrollable/wrapped claim list, inline marker spacing
and selection behavior, active marker border, and smaller mobile list height;
full-width subtitle cue styling does not fit these controls.

## Verification

Locally passed again after merging main `5eaaab4` (PR #250):

- All 38 web test files, including 16 new claim timeline/navigation tests.
- Existing source-window, card/mistake, transcript virtualization and Markdown
  regressions.
- 31 backend claim/API, semantic/gold and document-citation tests with the
  offline network guard and telemetry off.
- 35 script tests covering release-tree completeness, dependency boundaries,
  JavaScript imports, UI contracts and accessibility contracts.
- Synthetic fixture creation and read-only edition/claim/transcript/QA API
  checks under the same guard. Actual persisted maps then passed the frontend
  revision/span/interval validator. No model calls or real user data were used.
- JavaScript syntax, localization audit, architecture checks and release-tree
  audit tests, including rejection of a missing bundled claim-timeline module.

The existing Windows Edge `evidence-source-acceptance.cjs` now covers real local
playback of generated silence, seeks, repeated/disjoint intervals, claim/card/QA
anchors, 203-cue virtualization, keyboard focus, no playback writes, edited
notes, subtitle-only mode, delayed map/navigation races, widths 390/768/1440 and
200% CSS zoom, with screenshots and a JSON report. Only its syntax/self-test was
run here. The browser flow must run in Windows CI; no cloud-localhost browser was
opened. Workflow PowerShell validation is also pending Windows because this
executor does not have PowerShell.

## Exact remaining #139 acceptance boundary

- The implementation for local subtitle/frame/claim/note following is present;
  the new actual-browser flow and screenshots still need the CI run for this
  exact commit. Node/DOM fixtures alone are not visual acceptance.
- Existing original-page/extension seek and mismatched-tab identity protection
  were preserved. This change does not claim a new real-site browser session or
  extension integration test.
- The 390/768/1440 and 200% CSS zoom flow is prepared, not yet executed here.
  Native Windows WebView/browser zoom and screen-reader acceptance are not
  established by that CSS zoom fixture and remain manual/native acceptance.
- An edited note without a matching persisted map intentionally declines
  synchronization. Automatically rebuilding or remapping personal editions is
  outside this bounded change; there is no fuzzy fallback.

## Resumed integration on 2026-10-11

The reader patch is integrated with main `2562266`, including the current note
editor and collapsible source-review groups. Entering edit mode invalidates the
claim map before the editor opens. Shared claim/source labels retain screen-OCR
provenance and its explicit unverified status; a direct OCR text match never
becomes a factual-quality claim.

The actual Edge flow now also records horizontal centering of both the note and
source panel in the available workspace at 390, 768 and 1440 pixels. Body prose
keeps its reading alignment. This uses existing layout rules and adds no broad
CSS rewrite. Geometry assertions and screenshots still require this commit's
CI; they are not yet evidence of a passed visual review.

The current architecture budget remains the main-branch 2,310-line allowance;
the older 2,270 figure above describes the original October 9 baseline only.
Independent integration review found and fixed three regressions: copied
source-review excerpts cannot become canonical note blocks, cancelled source
navigation cannot reopen through an older item load, and a newly published task
map refreshes independently of unchanged note text. The captured retry generation,
update time and map path reject late previous-version responses. Progressive
draft sections clear a previous full-note mapping.

Local integration validation passed 1,365 offline backend tests, 383 Node test
entries, 175 script tests (3 existing skips), and complete desktop discovery of
47 tests (1 Windows-only skip). Independent review repeated 32 related cases.
The real local API read generated claim maps, editions and 203-cue transcripts
for two synthetic tasks; the production frontend span/revision validator
accepted both persisted maps. No real model, site session or user video was
used. Exact-head Edge and native-platform boundaries above still apply.

After catalog recovery #277 merged, integration onto main `dbcef816` passed
1,397 offline backend tests and 398 Node entries; the same 175 script and 47
desktop checks passed with their existing skips. No backend implementation
changes are part of this timeline patch.

## Original-scope audit and corrections on 2026-10-16

The retained `e8c1146` Edge artifact already establishes generated local-media
playback, claim/note interval following, card and Q&A anchors, bounded transcript
rendering and 390/768/1440 layouts. Its 200% check is CSS zoom, not browser zoom.
The original subtitle-only fixture has no page URL, so it cannot establish a
return-to-original-page route. No real Bilibili/YouTube extraction matrix is added
as an acceptance requirement for this issue.

The bounded follow-up makes original-page and timed links visible outside the
virtual subtitle scroller. Original URLs remain unchanged. YouTube watch/share
links use the provider's timestamp-sharing format. Bilibili retains the original
page and separately names its [documented external player](https://player.bilibili.com/),
whose `t` and `p` parameters preserve time and part. Unknown/signed URL formats
show the original link with an explicit manual timestamp instead of claiming
that the page can seek. Nested ranges use the saved absolute `original_start`;
malformed or out-of-range coordinates do not become guessed time links.

Playback no longer unmounts the virtual cue under keyboard focus. Follow resumes
at the latest position after focus leaves only if the user's Follow choice is
still enabled. Current mounted cues expose `aria-current="time"`; no unrelated
mounted row represents an off-window current cue. Explicit Home/End/arrows keep
bounded rendering. Regressions include variable-height queued scroll events,
manual scrolling, disabled Follow and stale source cleanup.

The Edge acceptance now prepares provider-shaped synthetic page fixtures and
intercepts every non-loopback request before browser navigation. It covers
keyboard-opened timestamp/manual links without contacting those providers.
Its separate native-zoom helper starts a fresh no-extension Edge process, binds
all zoom keyboard input to that process's unique window, verifies DPR doubling
and viewport-width halving with CSS zoom and pinch scale unchanged, captures
screenshots, restores zoom and closes only the owned browser. A CSS or emulated
viewport result cannot satisfy this native check. Local tests and source review
are not a claim that this newly added native flow has already passed Windows CI.


### Original-tab seek correction and bounded growth

The immutable `extension/tests/fixtures/source-seek-closed-tab-v1.json` fixture
(SHA-256 `05fcae2f1c706140b58e990783b1aa63109817522339e01be3bae04653e451d6`)
reproduces the original bug without opening a platform: at `e8c1146`, a closed
requested tab 11 falls back to active tab 22 when its URL is identical. The fixed
listener returns `source_tab_unavailable` after querying only tab 11. It never
seeks the replacement tab. Existing canonical identity helpers now also bind a
seek to the displayed frame, media source and per-document/video token; the
content listener rechecks these synchronously immediately before `currentTime`
is assigned. Actual listener-chain tests cover frame aggregation, sidebar
message construction and rejection after same-URL document/video replacement.
The opaque token is extension-only and excluded from backend task/preflight/E2E
payloads and capture-storage writes. No new permission or capture request is added.

The independently reviewed #139 safeguards add real behavior, rather than a
pure module extraction. The exact, separately approved budget changes are:

| Boundary | Old actual | New actual | Old cap | New cap |
| --- | ---: | ---: | ---: | ---: |
| Capture scripts, UTF-8 bytes | 334,722 | 339,271 | 335,000 | 339,500 |
| `source-identity.js`, lines | 164 | 200 | 170 | 200 |

Actual capture growth is 4,549 bytes; the aggregate cap changes by 4,500 bytes,
leaving 229 bytes of headroom. All other file and aggregate caps remain unchanged.
Shared canonical/platform/stable-URL helpers are reused, and seek messages carry
only the necessary source identity fields. No unrelated code was compressed or
checks removed to meet the limits.

An offline synthetic Node 24.19.0 Linux/x64 VM comparison of `e8c1146` with the
final identity correction used seven interleaved rounds, 50 startup samples per
round, and 5,000 listener calls after 500 warmups per round. Median startup was
1.3066 → 1.3020 ms; content-listener time 1.94 → 21.87 µs; combined background and
content time 5.30 → 36.27 µs. Synthetic serialized sidepanel/content messages grew
124 → 467 / 42 → 450 bytes. Seek loops made zero fetch, cookie, injection,
autoplay or active-tab-query calls. The pre-existing startup heartbeat was
intercepted by a throwing offline adapter in both versions (357 attempts each);
no network request was sent.

These VM measurements exclude browser IPC and structured cloning. They are not
browser performance results or actual extension seek acceptance. The fresh
no-extension Edge web/native-zoom gate cannot establish extension permission or
real-site integration behavior; that separate workflow remains unexecuted here.

Local validation of this correction passed all 73 extension and 79 web test
files, 245 script tests (3 existing skips), syntax checks, and the complete
architecture boundary/size checks. Native zoom fault-injection coverage also
proves original setup failures survive diagnostic-write and cleanup failures.
Windows Edge runtime screenshots and the new native zoom report remain the
publication gate; these local results do not substitute for them.

The ordinary hosted extension smoke is also prepared to open its existing
loopback MP4 in a fresh owned tab, add synthetic caption cues and click the
production-rendered sidepanel timestamp. Its positive check requires a real
paused media seek, exact raw/canonical page, tab, frame and media binding, no
transient autoplay, and an unchanged identical-URL twin. Only after that click
does it replay the observed in-memory message for invalid time, changed part,
same-URL video replacement and a closed original tab. Tokens are not logged.
This uses the existing smoke launch and permissions; the separate native
permission-warning workflow remains untouched. Offline harness tests are not a
claim that these new real-extension checks have already passed hosted Edge.
