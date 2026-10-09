# Issue #143: classic task-list policy extraction

Date: 2026-10-09. Implementation and pre-split snapshot base:
`6279fca6c049d92dc1be2ef2af37c44c1c720bb9`.
Issue: <https://github.com/hurry060215-tech/learnnote-assistant/issues/143>.

This independently reversible stage extracts fourteen pure task-list functions.
It is partial progress; **keep #143 open**.

## Migration and public contract

```text
classic.html
  -> task-format.js
  -> task-display.js -> task-format.js
  -> task-list.js -> task-format.js / task-display.js
  -> app.js (DOM, mutable state, clock, API and persistence orchestration)
```

The frozen `LearnNoteTaskList` namespace exposes these contracts. Task records
retain the existing task schema; the module does not validate, migrate or save
them. Callers continue to escape labels when generating HTML.

| Exports | Explicit inputs | Outputs |
| --- | --- | --- |
| `taskAwaitingConfirmation`, `isActiveTask` | Task record | Existing queued-confirmation and active-status booleans |
| `displayTaskTitle`, `taskMediaDisplayName` | Task; optional title fallback | Existing title fallback or media basename strings |
| `hasExportableMedia`, `visualWindows` | Task | Media-availability boolean; existing windows or legacy frame-grid projection |
| `preferredInitialTask` | Task list | Original preferred task reference or null |
| `taskStudyRank`, `sortedVisibleTasks` | Task/list; selected task ID | Rank or a new stable array of original task references |
| `taskMatchesFilters` | Task; `{statusFilter, query}` | Existing status/search match boolean |
| `taskListFingerprint`, `taskListLiveFingerprint` | Task list | Unchanged structural/live JSON fingerprints |
| `recentTaskTime` | Task; current Date | Existing local date/time label, `昨天`, or empty invalid-date fallback |
| `noteVersionInfo` | Task; full task history | `{rootId, index, total}`, including existing orphan/cycle handling |

The five state-dependent globals remain adapters in `app.js`. Each call reads
the current selected task, filters, history or clock, rather than capturing their
startup values. Original Chinese time formatting, fallback priority, stable ties,
pending-confirmation filtering and fingerprint fields remain unchanged. The
media/window helpers move with their consumers so no callback into app is needed.
Neither dependency module imports app or reads DOM, storage or network state.

`classic.html` loads the helper after both dependencies and before app; app's
cache suffix changes with the extraction. Source deployments retain every helper.
Classic UI is already excluded from supported desktop bundles; both desktop
specs and the release-tree audit also exclude the new classic-only file. The
default desk entry point and its packaged dependencies are unchanged.

## Budgets and failure gates

| File/group | Before lines | After lines | Enforced ceiling |
| --- | ---: | ---: | ---: |
| `web/app.js` | 9,603 | 9,452 | 9,650 → 9,455 |
| `web/task-list.js` | 0 | 207 | 215 |
| app + format + display + list | 9,998 | 10,054 | New 10,100 combined ceiling |

App shrinks by 151 lines (1.6%). The complete extraction group grows by 56 lines
for the namespace, exports and compatibility adapters; this is not a claim of a
net bundle reduction. Existing format/display limits remain 210/225 lines.

The JavaScript graph recognizes the new namespace, rejects reverse/cross-layer
imports and cycles, and checks classic script order. Its transitive dependency closure for recognized pure classic contracts
must fit inside the explicitly budgeted group: omitting a helper from
the list fails even when that omission would reduce the measured total. Tests
exercise missing helpers, reversed order, cycles, omitted dependencies, aggregate
overruns and desktop package exclusions. No new CI workflow is needed.

## Compatibility evidence and verification

`web/tests/fixtures/task_list_boundaries_v1.json` contains 143 synthetic input/output
cases captured by executing the fourteen original function declarations from the
untouched base source, before editing the implementation. Its recorded app SHA-256
is `3f2a06f5e4bc7b650181a7d81aa2f3c79cf1a4064bfe7e36f120e72b712c693f`.
The snapshot uses a fixed UTC clock and includes unreadable titles, search evidence,
status combinations, selection precedence, stable ties, media/window fallbacks,
live versus structural changes, invalid dates, version orphans and cycles.

Independent tests freeze inputs, preserve reference identity, reject ambient
DOM/storage/network access, verify dependencies at module initialization and
exercise changing state/clock values through the original app call sites.
The full classic VM interaction harness loads the new module in runtime order.

Local cloud validation on this stage:

- Backend: **1,120 passed**, through `scripts/test-backend-offline.py` with external
  DNS/HTTP/socket and external yt-dlp requests blocked; synthetic/local fixtures only.
- Scripts: **161 run, 158 passed, 3 platform/tool skips**.
- Focused architecture/dependency/release checks: **35 passed** (also in scripts).
- Desktop launcher: **28 passed**.
- Web: **all 49 test programs passed**, including the 143-case new snapshot suite
  and the full classic interaction harness; **45 JavaScript syntax checks passed**.
- Architecture boundary/load-order/aggregate checks and `git diff --check`: passed.

No browser, provider, user data, media/model download, desktop application launch,
or release build was used. Packaging claims are checked source/audit contracts;
actual Windows packaging and visual acceptance were deferred to integration CI;
those final results are recorded below.

## #143 acceptance mapping and remaining limits

- Monolith reduction: advances the app.js criterion by one cohesive boundary;
  this small stage does not complete the significant-reduction requirement across
  app, CSS, API/downloader and all three extension scripts.
- Public inputs/outputs and offline tests: provided above, with pre-split snapshots.
- Schema/API/export compatibility: backend and persistence code are unchanged;
  original global UI entry points, labels, task references and fingerprints remain.
- Enforced dependency direction/cycles: covered by the existing CI architecture
  command, now including the new pure namespace and complete aggregate group.
- UI visual, real-extension smoke and long-task recovery: no new browser or live
  run is claimed. Actual UI acceptance was deferred to ordinary Windows CI after integration
  and passed as recorded below; no local/localhost browser route was used.
- Independent merge/revert: one code-only stage; no data migration or rebuild is
  required. Reverting it restores the previous functions and script loading.

No new dependency, network destination, permission, telemetry, credential access,
storage schema, API route or export path is introduced. Further app decomposition,
extension/API boundary work and combined runtime acceptance remain outside this
stage. The original local stage was followed by the integrated PR validation below;
issue closure is outside this increment.

## Final integrated validation

[PR #285](https://github.com/hurry060215-tech/learnnote-assistant/pull/285)
merged at `41eaa32c6157539b0e0db6e61dc5276f4b935402`. Final head
`bd9ceaea5939bca5f5cb119e42ec104d3ac21f56` passed all five triggered PR
workflow groups. Detailed CodeQL reported no new alerts and review threads
were clear. Its CI merge tree matched the locally verified tree
`f0ccbd2b373c36b2a073182a4c8729036c22d018`.

The final combined tree, including the independent resource-report and multi-cue
fixes, passed 1,131 guarded backend tests, 247 Node entries across 49 web and
69 extension files, and 222 script/desktop tests (four existing skips). The first
combined backend process ended without a result during an execution interruption;
only the fresh isolated rerun's completed 103.967-second result is counted.

Actual classic and desk Edge acceptance passed in
[UI run 37978467551](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37978467551),
including classic stylesheet loading, learning/encoding flows, responsive layout
and the real-backend personal-anchor scenario. Packaging smoke also passed in
CI. No native extension, signed installer, manual screenshot review or full
long-task recovery is inferred from those gates. These results leave #143's
broader acceptance requirements open.
