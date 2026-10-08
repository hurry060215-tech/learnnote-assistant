# Issue #143: classic task presentation extraction

Date: 2026-10-08. Integration base: `5d80a04110380e8b31caf62996d49403af129abf`.
Semantic snapshot base: `01e10aa99ce56e6b769a95f992efd4e9bcd6f5e0`.

Issue #143 remains open. This stage moves 34 pure formatting and display
functions out of the classic application orchestrator.

- app.js: 9,903 → 9,599 lines; ceiling tightened to 9,650.
- task-format.js: 191 lines, ceiling 210. Owns escaping, times, sizes,
  filename decoding, safe header names and compact text.
- task-display.js: 204 lines, ceiling 225. Owns source/playback labels,
  model diagnostic text and processing-option projections.
- display depends only on format. Neither module needs DOM, storage,
  model access or network access.
- classic.html loads format, display and then app. Existing global names
  are preserved. No framework, task/API/export schema or persisted data changes.
- Both classic-only modules remain excluded from supported desk desktop bundles,
  with matching release-tree checks.

Verification: all 29 Web test programs passed, including the full classic
Markdown/interaction harness and independent semantic snapshots generated from
the exact pre-split base source. All Web JavaScript syntax checks passed.
The scripts suite ran 117 tests: 114 passed, 3 platform/tool skips.
Architecture and staged diff checks passed. Backend implementation is unchanged.

Real-browser visual acceptance is left to remote CI; no local screenshot
acceptance is claimed. Further app/CSS/content/page-hook decomposition and the
JavaScript dependency graph remain separate work. No migration is required;
this stage is independently reversible with its two helper files/load entries.
