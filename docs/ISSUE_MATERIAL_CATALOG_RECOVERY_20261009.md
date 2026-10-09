# Explicit material catalog recovery (#276)

The storage dialog now offers **恢复学习资料目录** separately from task-index
restore. Select a SQLite snapshot, inspect its preview, then explicitly apply
that same snapshot. Nothing silently selects a backup or reimports original
documents with new identities. The existing task restore still has
`backup_scope=task_index_only`.

## Recovery contract

- Catalog status reports healthy, missing, corrupt or incomplete state and
  original-material directories absent from the catalog. Task rebuild returns
  `blocked` for corrupt or documents-only missing catalogs. If independent task
  manifests can be rebuilt, it reports `partial` and the unresolved documents;
  it never claims complete recovery with zero indexed tasks. Status/startup do
  not create a missing database while orphaned documents remain.
- Preview validates the selected SQLite schema, types, sizes, canonical owners,
  IDs, source URI, original byte size and SHA-256, exact decoding revision,
  locators and full evidence text. OCR uses only the selected, validated local
  cache; it never runs a recognizer or model. Paths are rebuilt from validated
  IDs and filenames; stored absolute paths are never followed. Symlink targets
  are refused.
- The snapshot is the explicitly selected historical metadata authority. If
  current metadata is lost, original bytes cannot prove which historical title,
  encoding or cache selection was most recent. The UI discloses that limit.
  Surviving conflicting metadata, unverifiable originals/cache, absent evidence
  or orphaned originals missing from the snapshot block apply.
- Only document catalog and missing document-evidence rows are recovered.
  Video aliases are explicitly excluded and require their original task.
  Existing material rows, task rows, unrelated SQLite tables, course/group
  history, personal notes and study records are preserved.
- Preview is read-only for catalog/source data. Apply is bound to the selected
  snapshot hash and current database/source inventory. Changes require another
  preview. A shared reentrant process/file guard covers catalog connections and
  material mutations, including application processes on Windows and POSIX.
  Closing the dialog does not cancel an already started recovery; reopen it to
  check the resulting catalog state. The progress message states this explicitly.
- Before any write, `exports/catalog-recovery-<id>/` receives exact original
  database/sidecar bytes, copies of all material source/cache files, and a hash
  manifest. These recovery backups are never included in rotating snapshot
  cleanup. Existing healthy databases merge in one SQLite transaction; missing
  or wholly unreadable databases publish a complete staged database with atomic
  replacement. Failed validation, interrupted transactions and publication
  failures preserve the original database and sources.

## Finding and preserving rollback data

Successful recovery reports the actual `rollback_directory`; the UI displays
`数据文件夹/exports/<rollback_directory>`. Use the existing **打开数据文件夹**
button to locate it. Its `preserved.json` lists SHA-256 hashes, copied directory
entries and whether the original database was missing. It contains the exact
prior `library.sqlite3` when present, its available SQLite sidecars, and the
entire `materials/` subtree of originals and caches. WAL shared-memory bytes are
preserved for inspection but excluded from preview identity because ordinary
readers update that bookkeeping file.

Before manual recovery, fully close every LearnNote/backend process and first
copy the complete current data folder elsewhere. Keep the recovery directory
and its manifest unchanged. Verify each copied file against `preserved.json`.
Inspect a separate working copy of the database together with its matching WAL
or journal; never mix sidecars from different versions or overwrite the sole
copy. A preserved corrupt database is evidence for salvage, not a validated
replacement. If the prior database was missing, this backup cannot recreate
lost metadata that was absent at recovery time. The application deliberately
does not provide an automatic rollback-overwrite action; select a verified
snapshot and preview it, or obtain SQLite recovery assistance for damaged or
unresolved transactions. Group/history and other data files were never changed
by this operation and should not be replaced from unrelated backups.

## Deliberate bounds

This is not arbitrary SQLite salvage. Partially readable corruption is refused,
because replacing it could lose healthy records absent from the selected
snapshot. Corrupt/missing catalogs with unresolved WAL or rollback-journal files
are also refused. Preserve the complete data folder for manual recovery in
these cases. Original files alone are insufficient when metadata is unavailable.

Snapshots are limited to 128 MB, 5,000 materials and 100,000 evidence rows.
The preserved catalog/material inventory is limited to 512 MB and 20,000 paths;
each verified original/cache is limited to 32 MB. Exceeding a bound fails with an
actionable message, not truncation or partial success. Snapshot format 3 is
supported; no new database framework or background migration is introduced.

## Validation

`backend/tests/test_catalog_recovery.py` exercises the actual FastAPI app and
lifespan using temporary synthetic `/data` roots, plus exact hash/ID/provenance
round trips, OCR cache revisions, healthy-record/history preservation, invalid
schemas/paths, stale previews, failed publication, rollback after durability
failure, a competing app process, and process termination before commit.
The existing offline backend runner blocks external network and provider calls.

`web/tests/material_catalog_recovery.test.mjs` covers selection, unresolved
reasons, repeated clicks, late responses, close/navigation and failed apply.
`scripts/material-catalog-recovery-acceptance.cjs` uses the real application
assets in Microsoft Edge with isolated synthetic API responses. It is connected
to Windows UI CI and saves screenshots plus a report; a local browser run is
not claimed. Backend recovery is verified by the real-app Python tests.
