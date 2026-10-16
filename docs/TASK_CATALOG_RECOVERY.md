# Explicit task-only catalog recovery

This is a local fallback for issue #142 when the SQLite catalog is missing or
wholly unreadable but task manifests and their text sources remain intact. It
does not run at startup, during normal index rebuild, or automatically after a
failed graph request. No model call, migration, source rewrite, or document
re-import is performed.

## User flow and scope

In Settings → Storage → storage tools, use “损坏目录：仅恢复任务”. First request
a preview. It reports the recoverable task/evidence count, the unknown-document
boundary, and the offline rollback instructions. Applying requires a separate
confirmation button bound to that preview. Cancel, another source selection,
closing, or navigating away invalidates pending previews. Closing after apply
starts does not promise to cancel an already-running disk operation.

The API is POST `/api/library/catalog/tasks/preview`, followed by POST
`/api/library/catalog/tasks/apply` with the returned `preview_token` and explicit
`confirm_scope: "task_catalog_only"`. The token binds actual catalog-family,
task-manifest, and canonical text bytes. Apply reacquires locks, recalculates the
plan, and rejects changed sources. No client-supplied path or task payload is
accepted.

Only task rows and their ordinary note/transcript evidence projection are
reconstructed. Existing evidence IDs, locators, text revisions, source identity,
and course grouping files are retained. Video registration aliases, imported
documents, arbitrary evidence, and other catalog-only records are not restored.
Their lost count is unknown, even when no orphaned original directory remains.
The new database persists this warning and the original backup identity in
`library_meta`; catalog status remains incomplete across reopen and normal
task-index rebuild. Restoring some documents later cannot prove all unknown
records were recovered, so it does not clear the warning.

## Fail-closed checks

- No replacement if SQLite can still read its schema, including partially
  corrupted catalogs and incompatible versions. A document snapshot/full-data
  recovery must account for those records instead.
- Any nonempty WAL/rollback journal, unknown sidecar, symlink, Windows junction
  or other reparse point disables replacement. Known zero-byte logs are inert;
  their presence and exact bytes are still retained. SHM bytes are also retained.
- Invalid/duplicate-key manifests, mismatched IDs, future task versions, active
  queued/running/cancelling tasks, missing sources, and out-of-task text paths
  disable the whole apply. No silent skipping or automatic migration occurs.
- Inventories are bounded: at most 20,000 family files and 6,666 manifests;
  each manifest/text file is at most 16 MiB and each text at most one million
  characters. Catalog-family and task-source byte budgets are each 512 MiB.
  Source limits are checked before reading/loading the next file.

## Backup and activation sequence

1. Acquire the existing assistant-operation, task-state, library, and catalog
   locks in compatible order; validate source and lock paths.
2. Recompute the preview from actual bytes. Copy the whole original catalog
   family to a unique `exports/catalog-recovery-<random>/` directory using the
   existing durable backup primitive. Verify every copy; save `preserved.json`
   (including original absence) and `RESTORE.txt`. Recovery backups are never
   overwritten or automatically pruned.
3. Build a separate trusted-schema task catalog, rebuild task evidence, write
   the persistent partial marker, run SQLite integrity validation, and fsync it.
4. Recheck the plan. Move inert sidecars out of the new catalog family, preserving
   them in the backup directory; rehash the moved files and the remaining
   original DB before atomic replacement. Changed sidecar bytes abort activation.
5. Atomically replace the main DB and sync the data directory. An exception or
   caught interruption restores the original family. A process/OS crash can
   leave the new partial catalog or the old corrupt state; the durable original
   family and offline restoration instructions remain available.

Fault-injection tests cover process interruption and detected I/O failures. They
do not establish power-loss durability on every operating system or filesystem;
the existing directory-sync primitive is a no-op on Windows.

## Manual rollback restores bytes, not guaranteed usability

The original DB may be corrupt. Do not upload that file to the normal validated
SQLite snapshot restore endpoint. To undo the task-only replacement:

1. Fully stop LearnNote and all backend processes using this data directory.
2. Move the current `library.sqlite3` and every `library.sqlite3-*` sidecar into a
   different, newly created backup folder. Keep them; do not delete or overwrite
   either backup family.
3. Read the original backup's `preserved.json`. Copy only its `files` entries,
   with their original filenames, into the data directory. Files absent from
   the manifest must remain absent. Do not copy `original-` or `interrupted-`
   files from the recovery transaction as additional SQLite sidecars.
4. Restart only after the exact original family is in place. This restores the
   original corrupt/missing state, not a promise that the old catalog will open.
   Preserve the backup for a separately chosen full-data/document recovery.

## Validation

`backend/tests/test_task_catalog_recovery.py` covers exact evidence and cited
graph reconstruction, grouping history, missing and corrupt catalogs,
unknown-document persistence, all inert sidecars, unresolved logs, partial
readability, malicious/changed sources, changed sidecars during activation,
interruption rollback, source budgets, and explicit API scope.

`web/tests/material_catalog_recovery.test.mjs` covers preview/apply separation,
cancellation, stale navigation, repeated clicks, errors, persistent warnings,
and preserving confirmed success if a subsequent list refresh fails.

The existing hosted Windows Edge helper
`scripts/material-catalog-recovery-acceptance.cjs` now includes actual-app
task-recovery states and narrow/light and desktop/dark screenshots. Native
Windows and visual screenshot acceptance must run in that hosted environment;
Linux unit tests and synthetic reparse checks do not substitute for it.
