# Classic visual-study renderer boundary (#143, 2026-10-17)

This independently reversible stage moves the classic visual-study projection
and renderer out of `web/app.js`. It does not change the native reader, styles,
markup, task schema, API/export paths, capture permissions, or persistence.

## Migration and ownership

```text
app.js (DOM, event handlers, navigation, selected task, backend origin)
  -> visual-study.js (evidence state, review priority, escaped study HTML)
       -> task-format.js (escaping, timestamps and labels)
       -> task-list.js (task title, media availability, window projection)
       -> visual-window-evidence.js (subtitle overlap, summaries, review cues)

app.js supplies four current-policy callbacks to the renderer factory:
  safeNoteMediaUrl, hasTaskDiagnostics, taskExportUrl, taskClipExportUrl
```

The module never reads app globals, DOM, browser state, storage, timers or the
network. Its factory captures callbacks without calling them. URL sanitization,
current backend origin and the optional task-link provider are resolved by the
unchanged app callbacks on every render, rather than copied into this module.
This isolates visual-study presentation changes from UI lifecycle and export
policy changes. Input task/window/transcript records are never mutated.

The eight original function bodies are byte-identical to commit
`d2b4ef09e48b7be0e21675603dba0d777c31ebf8`. Their contiguous block is 367 lines,
20,087 UTF-8 bytes, SHA-256
`92461f29d014530ab1155b1486e1cec0c6dd82c7fd4b78d9eeedfb60c9ea4d2c`.
Existing app-global function names remain available. No DOM assignment, listener,
request, timer, selection or navigation handler is moved or rewritten.

## Public inputs and outputs

`LearnNoteVisualStudy` is a frozen namespace with
`createVisualStudyRenderer({safeNoteMediaUrl, hasTaskDiagnostics, taskExportUrl,
taskClipExportUrl})`. Its four required functions retain the app's existing
signatures: `(value) -> escaped local URL or empty string`, `(task) -> boolean`,
`(task, type) -> URL`, and `(task, windowId) -> URL`. Rendering preserves callback
errors and does not add retries, catches, requests or fallback behavior.

The factory returns a frozen object exposing:

- `visualWindowEvidenceState(task, window, index = 0)`: existing
  `{state, label, detail}` record. Missing evidence takes precedence over omitted
  evidence, then visual-model evidence, then the local-index state.
- `visualWindowReviewItem(task, window, index = 0, transcript = null)`: existing
  review-priority record, including the original `window` object reference.
- `visualStudyCorrelationHtml`, `visualStudyOverviewHtml`,
  `visualStudyReviewPathHtml`, `visualStudyHandoutHtml`, `visualStudyDeck`, and
  `visualStudyNavigatorHtml`: `(task, transcript = null) -> HTML string`;
  no windows returns the same empty string. Existing 10/6/8-window display
  limits, review ordering, fallback IDs, escaped attributes and action targets
  remain unchanged. Deck/navigator continue to use the full window list.

These functions accept the same task records and optional transcript object as
before, including legacy `frame_grids`. They introduce no new validation or
normalization of malformed inputs. Changing the current task or callback policy
is immediately reflected in subsequent renders; the module keeps no cache.

## Exact budgets and loading

| Surface | Before | After | Enforced cap |
| --- | ---: | ---: | ---: |
| `web/app.js` | 9,116 lines | 8,757 lines | 8,757 |
| `web/visual-study.js` | absent | 387 lines | 387 |
| Complete classic task-script group | 10,096 lines | 10,124 lines | 10,124 |

The previous aggregate cap was 10,100. This stage has a specifically approved
24-line cap adjustment, funding exactly 28 interface lines: a 20-line readable
namespace/dependency/factory shell plus eight app-wiring lines. Four lines were
already available. There is no extra headroom, unrelated deletion, whitespace
compression, uncounted helper, or change to any other budget. The eight bodies
are moved verbatim; the measured increase is explicit, not a claim of aggregate
size reduction. Architectural separation and the smaller orchestration boundary
are the benefit of this stage.

`classic.html` loads all three providers (and their dependencies), then
`visual-study.js`, then `app.js`. The new script and app share cache key
`20261017-visual-study`; other asset keys are unchanged. The JavaScript graph
allows only the three declared provider edges, rejects reverse/cyclic imports,
and prevents the renderer or transitive dependencies escaping the aggregate
budget. Both current desktop specs exclude the classic-only asset, and the
release-tree audit rejects its accidental inclusion. The immutable historical
native rollback fixture is untouched. The active `index.html` is unchanged.

## Regression and acceptance evidence

`web/tests/fixtures/visual-study-d2b4ef0.json` freezes all six HTML results and both
record projections for 19 synthetic pre-extraction cases. Its explicit opt-in
regenerator reads the original commit with `git show`, never the extracted
implementation:

```sh
node web/tests/helpers/generate-visual-study-snapshot.mjs --write
node web/tests/visual_study.test.mjs
node web/tests/markdown_render.test.mjs
python -m unittest scripts.tests.test_javascript_graph scripts.tests.test_architecture_graph scripts.tests.test_release_tree
python scripts/check-architecture.py
```

Cases cover empty/legacy input, evidence-state precedence, fallback IDs, review
priority, stable ties and 6/8/10 limits, overlap endpoints, missing/negative/zero
times, Unicode truncation, hostile text, rejected remote media URLs, current
backend origin, and fallback export links. Tests verify exact function hashes,
frozen exports, immutable input and window identity, no ambient browser effects,
no construction-time callback calls, repeated task rendering, live policy/link
replacement, failure propagation, load order, matched cache keys and native
exclusions. The existing full classic Markdown/UI harness loads the new module
and retains its original behavior assertions. Graph mutation tests reject bad
load order, reverse edges, cycles and omitted budget members.

Actual browser screenshots remain a required integrated-tree hosted classic UI
gate. This cloud executor cannot provide that browser evidence; offline HTML
parity is not a visual acceptance claim. The stage does not close #143, claim
long-task recovery, or change the intentionally inactive historical page hook.
Rollback consists of reverting this one extraction commit, restoring the old
app bodies, script tag, native exclusions and graph/budget registrations together.

Fresh local validation on the reconstructed 4d8ec2f-based tree: all 92 web test
programs pass; script unittest discovery runs 330 tests successfully (three
platform-specific skips); desktop launcher tests pass 28/28. JavaScript syntax,
architecture checks and diff whitespace checks pass. Regenerating the frozen
snapshot twice produces the same SHA-256
`51d653368b012c833d3345eed33de816948262f8dab53c745969bd42fb934a67`.
No local browser, publication or hosted workflow dispatch was performed.

Windows-checkout portability: source-boundary and provenance comparisons
canonicalize CRLF to Git's LF form, without changing any other source bytes.
The complete contract executes both LF and CRLF provider/renderer sources and
compares all 19 cases against the same immutable baseline. Product sources and
expected HTML/record fixtures are unchanged by this test-harness correction.
