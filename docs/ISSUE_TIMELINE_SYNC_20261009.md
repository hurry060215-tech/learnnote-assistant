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
