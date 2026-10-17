# Move a desktop data directory safely

The stopped-copy and native restart path has passed the
[unsigned macOS arm64 acceptance](qa/20261017-native-data-migration.md).
Windows/macOS/Linux automated migration contracts also pass. This does not claim
an actual native folder-dialog interaction or automatic foreign-root migration;
the precise supported scope and failure behavior are below.

Use **Settings → Data location → Change location** in the desktop client. The
first step is a preview. It does not change the active directory, merge folders,
or rewrite the source. Choose an existing **empty** folder outside the current
data directory. Windows continues to require a non-system drive.

1. Finish or stop tasks, and close other LearnNote processes using this library.
2. Check the source, destination, file/byte counts, exact path changes, exclusions
   and external-file references in the preview. Cancel leaves the active data and
   configuration unchanged.
3. Save any open editor/settings changes. Choose **Confirm copy and restart**.
   The client exits first. A helper waits for the whole original process to exit,
   checks its existing desktop, catalog, worker, personal-data, assistant-operation, course and task-state locks without creating source lock files, and verifies that the approved source snapshot has
   not changed. It then copies and validates a separate staging directory.
4. The helper activates the destination only after every validation succeeds.
   Settings shows the last outcome and the local receipt path after restart.
   “Scheduled” is not confirmation that copying finished.

The source is retained. Source files, their contents and modification times are
not changed by migration. Configuration is committed last, and its exact previous
bytes are saved beside the receipt. Unknown configuration keys are retained.

## What is copied

Supported app-owned tasks, uploads, materials, raw imports, courses, learning
spaces, personal notes/editions/reviews, study backups, assistant records, exports,
static assets, supported preferences and local databases are copied. Only the
explicit, verified task-artifact and catalog path fields shown in the preview are
changed in the destination. Task IDs, source/range identity, revisions, hashes,
non-path JSON bytes, catalog row counts and non-path SQL values are preserved.

Known task JSON fields, visual-index image/grid references and summary-diagnostic
references are checked against the exact source snapshot. Cross-task dependencies
require the existing explicit, bounded source-task ancestry; sibling searches or
basename matching are never used. Catalog updates are limited to
`library_tasks.note_path/media_path`, `library_materials.stored_path` and the direct
`metadata_json.ocr_path` property, with manifest/material ownership proof.

SQLite main files and their complete stopped WAL/SHM family are preserved in the
source. Integrity checks and any WAL consolidation run only on disposable copies.
The current catalog schema (version 3) and exact current schemas of the six other databases are
supported. Table definitions, constraints, indexes, required tables and both SQLite version identifiers must match the supported signatures. Older or unknown schemas stop with a diagnostic. No database schema upgrade or rollback-journal recovery is attempted.

## What stays at its original location

Browser profiles, cookies, credentials, temporary upload state, process locks,
model caches and old installer/update staging are excluded before traversal.
The preview lists the exclusions. Provider settings may need reconnection after
the move because credentials are not transferred. Models can be downloaded again.

External originals are not copied or relocated. Their metadata is preserved and
listed for review without opening those external paths. Keep those original
files at their existing location if you still need media reuse.

## When preview or activation stops

Nonempty/overlapping destinations, links/reparse points, special files,
case-colliding names, unsupported schema/path fields, missing task ancestry,
missing owned artifacts, incomplete restore state, rollback journals, orphaned
SQLite sidecars, active/unknown task states or a changed source snapshot stop the
operation. The production artifact resolver remains strict; migration does not
add a general fallback to old absolute paths.

A normal shutdown can change a database snapshot after preview. If that happens,
activation is cancelled rather than accepting an unreviewed copy. Reopen the
original library, let pending writes finish, then preview again. If the blocker
persists, retain the original and use the receipt to diagnose the specific cause.
Do not discard journals or edit unknown path fields to force migration through.

This desktop flow maps the explicitly selected native source root to the selected
native destination. It does not infer a mapping for a previously copied foreign
or unrelated absolute root, upgrade an older catalog, or rebuild a corrupt one.
Those cases need a separately reviewed mapping/recovery procedure. Existing
read-only compatibility for copied Windows task-owned text artifacts is distinct
from this explicit whole-directory move.

## Interruption and recovery

Receipts and the exact previous configuration are kept under
`<application directory>/.data-migrations/<request id>/`. The receipt contains the
approved roots, source/file hashes, exact changes and database preservation proofs.
It contains no copied credential or browser-profile contents.

Before the atomic configuration replacement, a failure or interruption leaves
the old configuration active. A partial stage or a complete but inactive copy may
remain; the app will not merge into or silently delete it. Preserve it and the
receipt while investigating. Choose a different empty destination for a new
attempt. After configuration replacement, a receipt marked `ready_to_activate`
can be reconciled as complete only when the current config hash matches its
recorded next-config hash.

To return to the retained source, first close LearnNote and all of its backend
processes. Preserve any work created in the destination after migration; it is not
present in the older source snapshot. Check the receipt and keep a copy of the
current config. If a `previous-config.bin` exists and matches the receipt's
previous-config hash, restore those exact bytes to `learnnote-config.json` in the
application directory, then reopen. If no previous config existed, or hashes no
longer agree, retain both directories and seek a reviewed recovery rather than
merging or deleting files. There is no automatic downgrade or merge of newer data.
