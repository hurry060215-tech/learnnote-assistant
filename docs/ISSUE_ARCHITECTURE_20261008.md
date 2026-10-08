# Issue #143: independently mergeable backend decomposition stage

Date: 2026-10-08. Integration base: `dc257c83fc939582ca86c7cf3f7bc9b06cffb72c`.
Pre-split behavior snapshot base: `632b6076e847b3b1baa256c760e18f81a4821183`.
Issue: <https://github.com/hurry060215-tech/learnnote-assistant/issues/143>.

## Result and scope

This stage substantially reduces downloader orchestration and extracts API-adjacent
QA policy/serialization without changing APIs, task schemas, saved history, export
paths, permissions, telemetry, or framework. It is **partial progress, not a claim
that issue #143 is complete**.

| Entry point | Before | After | Reduction | Enforced ceiling before → after |
| --- | ---: | ---: | ---: | ---: |
| `backend/app/main.py` | 5,132 | 4,735 | 397 / 7.7% | 5,200 → 4,800 |
| `backend/app/downloader.py` | 3,694 | 2,748 | 946 / 25.6% | 4,200 → 2,800 |

New modules and their explicit contracts:

| Module | Lines | Public inputs / outputs |
| --- | ---: | --- |
| `media_url_parsing.py` | 250 | Supplied URL/text/base URL → normalized URLs, decoded candidates, lexical hints |
| `media_json_discovery.py` | 414 | Supplied JSON/field/encoded text + base URL + source label → existing `ResourceCandidate` values |
| `media_discovery.py` | 299 | Supplied HTML/text + base URL + source label → bounded media/player-frame candidates |
| `media_manifests.py` | 133 | Supplied manifest text/base URL → kind, DRM/AES flags, rewritten manifest text |
| `qa_evidence.py` | 378 | Citation dictionaries, transcript segments, query text and explicit policy callbacks → same citation/text projections |
| `qa_history.py` | 112 | Existing task/request/result + explicit storage/clock/ID callbacks → version-1 history and unchanged Markdown |

The migration/dependency map is in `docs/ARCHITECTURE.md`. No new module imports
`main`, `downloader`, or `processor`. Importing the new modules does not load these
entry points. Downloader keeps the historical helper exports. Main keeps current
route/function names and resolves mutable storage/trust callback adapters at call
time. Model execution, network security and task lifecycle remain in their existing
owners.

## Enforceable checks

- New modules have individual ceilings between 130 and 440 lines.
- The explicitly listed extraction group has a combined 9,250-line limit
  (current 9,069), bounding the moved code as well as the original entry points.
- `processor.py` ceiling: 1,700 → 1,450.
- Historical `web/app.js` ceiling: 10,000 → 9,950; `web/styles.css`: 13,500 → 12,920.
  These small reductions freeze growth; they do not represent a new Web split.
- Extension `page_hook/background/content` ceilings: 2,850 / 2,950 / 2,200 lines;
  combined capture-script byte ceiling: 335,000 (current 322,902).
- Static import analysis covers absolute, relative, aliased, `from package import
  module`, and function-local imports. Strongly connected components fail the
  existing architecture CI command, as do forbidden cross-layer imports.
- Exactly three existing **deferred** lifecycle edges are enumerated as migration
  debt: `library → study`, `storage → task_queue`, `task_queue → range_learning`.
  No whole-module or whole-cycle exception exists. Eager versions of those imports
  and any other newly introduced cycle are rejected.
- New tests deliberately introduce cycles, aliases, forbidden leaf-to-storage
  dependencies, eager legacy edges and size overruns, verifying failure behavior.

## Compatibility evidence

`backend/tests/fixtures/architecture_extraction_v1.json` was generated from the
exact pre-split base commit, not from the refactored implementation. It records:

- JSON, split-base JSON, malformed JSON, HTML, escaped and percent-encoded media;
- HLS/DASH URI rewriting, malformed DASH fallback, AES/DRM flags and HTML rejection;
- note cleanup, transcript windows, citation order, timeline sampling, prompt text;
- QA, streaming QA, QA export, bundle export and manifest-export OpenAPI paths.

Independent tests cover current main monkeypatch points, caller-supplied policy,
legacy list-shaped history, current version-1 history, exact storage filenames,
and module imports without API/pipeline initialization.

## Verification

Executed in the cloud checkout with the shared Python 3.12 test environment:

- Full backend suite using current-main `scripts/test-backend-offline.py`:
  **675 run: 674 passed, 1 skipped** (optional OCR runtime not installed).
- Full `scripts/tests` discovery: **107 run: 105 passed, 2 skipped**.
- Desktop launcher suite: **28 tests passed**.
- Focused extraction + dependency graph tests: **18 passed**.
- `compileall backend/app` and architecture checker: **passed**.
- JavaScript syntax checks: **5 entry scripts plus upstream-changed `desk-settings.js` passed**.
- Extension regressions: **all 59 `.test.mjs` programs passed**.
- Web Markdown regression: **passed**.
- `git diff --check`: **passed**.

The backend runner blocks external DNS, HTTP/socket access and external yt-dlp
fixture requests. No real account, provider model, paid API, desktop, release,
store submission or external course capture was used. Earlier local extraction
iterations exposed missing parser helper imports; those were corrected before the
successful final complete backend run.

FastAPI reports a pre-existing duplicate operation ID for the study export-presets
route when building OpenAPI, also reproducible from the unchanged base source. This
stage does not modify that unrelated route.

## Closure eligibility and remaining gaps

**Do not close #143 after this commit.** It is eligible for an independent stage
merge once integration CI passes, but the epic still requires:

1. Material decomposition of Web app/CSS and all three extension entry scripts.
2. A JavaScript dependency-direction/cycle guard; this stage enforces the Python
   graph and extension size budget only.
3. Continued reduction of main's remaining diagnostics, API orchestration and
   export responsibilities, and removal of the three deferred integration edges.
4. Real-extension smoke, UI visual acceptance and long-running recovery evidence
   on the combined changes. Browser localhost access in this execution environment
   is policy-blocked; no workaround or bypass was attempted.

No data migration or rebuild is required. Reverting this single stage restores the
original code organization while reading the same task/history/export artifacts.
