# Issue #143: background capture policy extraction

Date: 2026-10-08. Base: `01e10aa99ce56e6b769a95f992efd4e9bcd6f5e0`.

Issue #143 remains open. This is a bounded, independently reviewable stage after
the merged backend extraction.

## Scope and contracts

- background.js falls from 2,891 to 2,444 lines (447 fewer; 15.5%).
- capture-classification.js owns 18 pure URL/MIME/header/manifest functions,
  returning existing classifications, filenames and candidate URLs.
- capture-ranking.js owns 22 pure candidate comparison, playback-context and
  merge functions. It depends only on the classification namespace.
- background.js loads both packaged helpers synchronously before registering
  browser handlers. Historical global function names remain available.
- Tab state, explicit capture permission, cookies, network requests, storage,
  event handlers and source handoff remain in the background orchestrator.

No framework, dependency, manifest permission, telemetry, collection scope,
persisted schema or API change is introduced. The normal runtime still does not
inject page_hook.js.

## Packaging and bounds

The PowerShell package list, store validator, release-tree audit, macOS copy
list and managed desktop updater all include both helper files explicitly.
Desktop installation tests verify both files survive staged installation while
the prior version remains backed up.

background.js is limited to 2,500 lines; classification to 290 and ranking to 320.
The existing 335,000-byte capture bundle limit includes both helpers through
EXTENSION_CAPTURE_SCRIPTS. Other work adding capture helpers must add them to
that same bounded enumeration, without relaxing the limit.

## Validation

- All 61 extension test programs passed, including isolated pure policy tests,
  MIME/fragment behavior, filename decoding, ranking, merged resource fields,
  same-origin navigation isolation and missing/reversed helper load order.
- Existing VM tests execute the real synchronous importScripts load sequence.
- Scripts suite: 117 run, 114 passed, 3 platform/tool skips.
- Desktop launcher suite: 28 passed.
- New/changed JavaScript syntax, architecture guard and staged diff checks pass.

The full backend suite was not rerun for this background-only stage; backend
implementation files are unchanged. Remote CI verifies the combined branch.
No real-browser result is claimed from this local verification.

## Remaining work

The larger Web/classic extraction and JavaScript dependency graph are separate
follow-up stages. content.js, page_hook.js, styles.css and broader ownership
work remain part of issue #143. This stage requires no data migration and can
be reverted together with the helper files and packaging entries.
