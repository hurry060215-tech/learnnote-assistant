# Issue #143: JavaScript dependency and load-order gate

Prepared against main `fdadce2e6f96d27f2e4fca4c60d116b9be150788`.
This four-file stage changes checks only and has no dependency on unpublished
Study source. Issue #143 remains open. Future Study-helper behavior is exercised
with synthetic fixtures; a helper file is required only when actual source
references it.

The existing architecture CI command now checks:
- Local literal ESM imports, re-exports and dynamic imports.
- Classic importScripts dependencies and explicit executeScript file lists.
- Dependency cycles, missing modules, cross Web/extension edges and imports
  from pure helper modules back into orchestration.
- Capture classification before ranking, task formatting before display/app,
  and content-study-evidence before content.js in the separately injected realm.
- Every discovered capture dependency appears in EXTENSION_CAPTURE_SCRIPTS;
  the existing 335000-byte budget and all line ceilings remain unchanged.

Mutation tests exercise cycles, unsafe/computed module paths, missing files,
reversed and missing helper load order, cross-surface imports, and hidden budget
growth. String/comment/regular-expression examples are not mistaken for imports.

This is a bounded dependency lexer, not a replacement JavaScript parser or
arbitrary runtime analysis. Node syntax tests remain required. Existing deferred
UI callback globals are not eager module edges; five named pure classic
namespaces have explicit contracts.

No application source, permissions, telemetry, network behavior, data schema,
task file or export is changed. The standalone checker passes the actual main module graph, including merged
classic presentation modules. No future helper file is required on main.

Validation: 774 backend tests and 28 desktop tests passed; all extension/Web
test programs passed. Backend/application sources are unchanged by the final
workflow-only main rebase. Full scripts and architecture checks were repeated
after that rebase; 20 focused dependency/budget contracts passed.

PR #241 head `30eef3224e96ebb14a17f00d34360a4106fdc6a2` uses
`content-study-evidence.js` and `LearnNoteStudyEvidence`, exporting only
`collectChapterEvidence`. Its exact provider/pure rules are covered, including
reversed injection order, missing helper in the injected realm and a forbidden
import back into background orchestration. No Study application source is part
of this checks-only change.
