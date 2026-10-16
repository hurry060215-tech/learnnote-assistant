# Task artifact path portability (#70)

## Scope and ownership

The active data-directory selection defines `TASK_DIR/<task id>`. Configured
`DATA_DIR` and its higher ancestors are trusted and canonicalized by configuration;
filesystem link/type checks begin at the selected `tasks` directory. Saved task JSON
and artifact bytes are never rewritten by this resolver. Existing native paths
inside that exact task directory keep working. Task-relative references such as
`note.md` identify one canonical destination. Current producers still write
native absolute paths; this change does not migrate their persisted format.

A copied foreign Windows path on POSIX (or a foreign POSIX path on Windows) can
resolve only through a single exact `tasks/<same id>/<known artifact>` suffix.
The destination manifest must identify that task. Known text artifacts include
formal/review/partial/caption notes, transcript, visual index and task-root subtitle
files (including the known task-owned `downloads/` subtitle directory). Existing owned-source helpers also resolve known grid images. There is no
basename search or recursive candidate search. The destination must be a regular
file, with no symlink or Windows reparse point in the task root, tasks directory,
child directory, final file, or relocated manifest.

An outside native absolute path always needs a reviewed migration mapping. The
resolver does not even stat the old location to see whether another copy exists.
This narrow change supplies no migration-mapping preview API. Same-platform
absolute relocation and corrupt-catalog rebuilding from foreign-path manifests
remain gated until an explicit mapping is reviewed through a separate migration
workflow; there is no silent repair.
UNC/device/drive-relative/mixed/traversal/alternate-stream paths, ambiguous repeated
owners, mismatched task identities, missing files and unknown relocated artifacts
fail closed. Saved artifact reads return an HTTP 409 recovery diagnostic rather
than reporting an empty successful note/transcript. Availability projections carry
per-field diagnostics. Empty optional fields retain their existing empty behavior. An unresolved nonempty
current-note pointer blocks retry snapshotting rather than pretending the note is
absent; valid history remains readable with a current-note diagnostic.

## Covered read boundaries

- Main note/transcript/visual-index readers and their text/sanitized exports
- Canonical task manifest reads before following any recorded artifact paths
- Personal source/anchor ownership helpers and partial-draft projections
- Task readiness, subtitle reads/exports, course caption availability, note-history
  snapshot source and the saved-transcript worker’s read boundary
- Best-effort library text indexing, which never indexes unresolved outside data

The stored path remains historical metadata. Read-only resolution does not change
saved paths, task status, source bytes, credentials, or models. Explicit retries
retain their existing state/consent semantics; media is never automatically
relocated. The follow-on boundaries below cover full bundle subtitle/grid reads,
retry admission and known saved-path consumers. Arbitrary nested attachments are
not broadly repaired. Native packaging, signing and notarization remain separate
acceptance work.

## Synthetic validation

`backend/tests/test_task_path_portability.py` creates independent copied-foreign,
native POSIX/Windows and canonical-relative fixtures. It checks production API
reads, Markdown/subtitle/sanitized bundle export, source ownership and indexing;
compares original manifest/artifact SHA-256 values before and after; and covers
outside old paths present/absent without probing them, traversal, multiple owner
segments, sibling-task identity, missing/directory candidates, linked ancestors,
linked manifest/final files and mocked Windows reparse attributes. Mixed good/bad
manifest lists remain usable without reading linked files; strict recovery snapshots
still reject them. No real model
calls, user files, external services, or automatic repairs are involved.

Focused command (the extra tests path supports existing course test imports):

```sh
PYTHONPATH=backend:backend/tests python -m unittest \
  backend.tests.test_task_path_portability backend.tests.test_personal_anchors \
  backend.tests.test_personal_reviews backend.tests.test_full_response_drafts \
  backend.tests.test_progressive_sections backend.tests.test_course_upgrades
```

Run the full offline backend runner and script architecture checks before claiming
integration completion. Native filesystem behavior beyond the synthetic reparse
fixture still needs its platform CI run.

## Follow-on mixed-copy output guard

Full bundle subtitle/grid file copying now resolves the exact owned destination
before passing it to the unchanged archive serializer. Nonempty missing or unsafe
pointers fail with 409 instead of silently omitting attachments or mixing an old
copy into a new note. The original task paths remain in exported task metadata;
only the file-copy inputs/member basenames are projected. Frozen archive-byte
fixtures exercise serialization separately from this new admission boundary.

Resource inventory and page-preflight reads accept only their exact known JSON
artifact names on relocation. A nonempty unresolved saved pointer fails closed;
empty optional report pointers still return empty when the canonical file is absent.
Explicit retry-summary now validates its saved transcript with the same resolver
before any filesystem probe, while preserving the existing snapshot/consent rules.
This supersedes the earlier retry-summary and bundle-attachment scope exclusions
for these exact fields. Arbitrary nested attachments remain outside the mapping.

`test_task_export_boundary` covers old/new-copy mixing, no old-path stat/read,
missing attachment diagnostics, linked reports, byte preservation, and explicit
copied-transcript retry with dispatch/model work mocked.

## Follow-on media admission guard

Media is never automatically relocated. A pure lexical guard rejects reuse when
saved task-owned text/report provenance refers to a foreign/outside task root, or
when a media pointer claims a different `tasks/<exact same id>` root. Windows and
POSIX syntax are parsed independently; sibling IDs and prefix-similar paths are
not treated as the same owner. Rejected paths receive no stat, resolve, or read.
Direct preview/export, retry/resume, OCR source admission and restart recovery
apply this boundary. Availability stays false while explicit actions expose the
recoverable path diagnostic. Restart recovery uses its existing waiting-for-source
status, without changing path metadata or source bytes.

Current native uploads/original inputs and explicit source-task dependencies retain
their existing authority. Each media component is checked for links/reparse points
before the file is used. Native files below the configured data directory trust
that configured boundary; external original inputs are checked from their native
anchor. Nonempty subtitle inputs are also validated before retry admission mutates
a task. Legacy external-only manifests with no task-owned provenance cannot prove
that a directory was copied: their migration remains unsupported and no mapping
is guessed. Re-selecting/re-importing an original is an explicit user action.

`test_task_media_guard` covers old copies with read/stat guards, media/exports and
all retry/OCR entry points, exact Windows/POSIX ownership components, current media,
active uploads, cross-task dependencies, symlink files/ancestors, startup waiting
for source, and missing-subtitle rejection before state changes. Synthetic source
media bytes are unchanged and no media/model process is run.

## Consolidated saved-path caller audit

The following inventory describes the final bounded change, superseding the
reader-only exclusions in earlier review commits. Every rejected copied media
path is classified lexically before filesystem resolve/stat/read or media hashing.
Configured `DATA_DIR` and higher ancestors remain the trusted boundary; owned
artifact checks start at `tasks`. Explicit current external originals retain
native authority and are checked for links from their native filesystem anchor.

- `storage.get_task`, `list_tasks`, `list_tasks_snapshot` validate the manifest
  before reading it. Non-strict listing skips invalid records; strict catalog and
  recovery paths fail visibly. `reconcile_stale_tasks` leaves an uncertain copied
  record byte-for-byte and mtime unchanged. It does not turn a read/list into a
  migration or recovery mutation. Current legitimate stale recovery is retained.
- `task_artifacts` note/transcript/visual/report readers and `main` readiness,
  exports, report readers, resume-cache seed and retry-summary admission use the
  exact owned resolver. Full bundle copying resolves every subtitle/grid input;
  generated member references match those files while original metadata remains.
- `personal_anchors`, `section_review_sources`, `personal_notes`, `routers.notes`,
  `personal_review_context`, `partial_note_projection`, `course_caption_state`,
  `summary_versions` and `library.index_task` use the owned reader boundary.
  History stays readable independently of an unresolved current-note pointer;
  snapshot/retry cannot silently discard that pointer.
- `subtitle_notes`, `processor` prior-note checks and `progressive_sections`
  validate saved note pointers. `processor` saved-transcript OCR work checks media
  before hashing, including recovered summary jobs. `learning_spaces._live_source`
  resolves note/transcript pointers before hashing them.
- `task_inputs`, `screen_subtitle_routes`, `task_queue`, `range_media`,
  `course_upgrade_links.episode_upgrades`, `range_learning._create_range_task` and
  `library.register_task_material` use the cheap root-injected media guard.
  Listings do no FFmpeg or hashing. Unavailable copied media cannot be admitted,
  previewed, exported or registered by hashing an old file. Explicit current
  uploads and supported source-task dependencies remain usable.
- `subtitle_ownership.retain_subtitle_file` materializes an owned subtitle before
  a caption-only or text child publishes success. Source bytes are unchanged;
  copy/collision failures are not swallowed or replaced with a cross-task alias.
  The existing caption range-context producer remains unchanged.
- `document_exports._task_image` resolves declared grids and retains existing
  caption-only fallback for unavailable images. `visual_pipeline` validates native
  saved frame/window cache paths before reads; no foreign cache remapping occurs.
- `course_deletion._dependency_owners` checks only selected-root dependencies and
  fails preview for uncertain mappings or linked entries. `storage.delete_task`
  may clean up only a validated current owned upload. Outside copied originals
  are never probed or deleted; existing task-deletion authority is not broadened.
- `task_catalog_recovery` retains its separate strict native-owned boundary;
  corrupt-catalog rebuilding of copied foreign manifests is gated, not repaired.

Remaining raw-path operations have explicit non-manifest boundaries:
`task_archives` is an explicit-input serializer whose production bundle caller
supplies the owned adapter. Its byte-format fixtures test serialization separately.
`summary_diagnostics`, `summarizer`, `local_ocr`, subtitle parsers, downloader/upload
processors, `remember_reusable_media`, `screen_subtitle_tasks` and
`transcript_cache.media_cache_integrity` consume fresh pipeline outputs or inputs
validated by the public admission/queue/cache boundary. The `main` native media
missing/type fallback runs only after the strict guard; it preserves existing
404/400 behavior and cannot follow a rejected copied path. Metadata-only path
names/suffixes and exported historical JSON are not filesystem reads.

Explicit remaining limits: same-platform absolute relocation needs a reviewed
mapping; this slice has no mapping-preview control. Legacy external-only records
without task-owned provenance cannot establish a copied root and have no supported
automatic migration. Arbitrary nested binary attachments and foreign visual caches
are not guessed. Unsupported saved artifact mappings fail with recovery guidance
to check the selected data directory and explicitly reselect/reimport where the
application supports it. The `requires_preview` flag expresses a requirement, not
an implemented preview API.

`test_task_path_caller_regressions` exercises actual caption-only publication and
export, copy failure, mixed stale listing with manifest hash/mtime preservation,
OCR API plus worker, learning hashes, resource usage, grids, range preview, visual
cache, deletion preview and cleanup. `test_task_media_callers` independently covers
course/range/material registration with existing old files and denied stat, lstat,
resolve, open/read; positive current upload/cross-task cases remain covered.
Windows owner matching is case-insensitive only for Windows syntax; POSIX remains
case-sensitive. Native Windows coverage is explicitly skipped on POSIX and must
run in its hosted platform gate.

## Historical caption children and conservative optional cleanup

The actual older caption producer changed `rerun_from_media` to `subtitle_only`
and persisted `subtitle-extract`, keeping `source_task_id` and sometimes a
source-owned subtitle pointer. A read-only exception handles that precise state:
validated child/source manifests in the same selected root, exact source-owned
native subtitle, matching inherited page/part/resource/active-video/range data,
consistent child local media identity, and the exact validated current source
media under the selected data directory. Source input and child normalized-media
hashes are not equated. Contradictory saved entry routes, cycles, missing identity,
changed source, foreign roots and links remain recoverable failures. No arbitrary
sibling, recursive file search or external-only ancestry mapping is permitted.
One shared strict rerun-identity proof supports current child-owned subtitles and
bounded range-source traversal independently of subtitle placement. Historical
subtitle/bundle export and media provenance add the precise old caption state and
identical recorded subtitle pointer at every explicit `source_task_id` hop, ending
at one owned regular file within 16 hops. No sibling or basename search is used.
Future caption children retain their own subtitle before parsing, so transcript
and exported subtitle describe the same snapshot. An explicit summary retry
retains an already-validated historical alias into the child before changing
options or dispatch; copy/collision failure rejects before task mutation. Later
summary generation cannot invalidate the now-owned subtitle export. Ordinary
reads remain non-mutating projections.

`test_historical_subtitle_ancestry` uses real rerun API admission and the historical
caption-finalization boundary, including differing original/normalized hashes. It
checks fresh and historical caption children, exact multi-hop aliases,
export/retry/export through actual saved-transcript generation with an offline
summary fixture, unchanged ancestor bytes/timestamps, and negative
source/range/part/identity/route/cycle/depth/foreign/link/copy/collision cases.
Missing historical proof never rewrites a manifest.

Optional upload cleanup now requires complete no-follow task-entry enumeration
and strict validated survivor manifests. A surviving pointer must identify a
regular link-free file under current task/upload roots, with a known different
file identity from the validated upload, before independence is established.
Lexically different hard links or native short/long-name aliases remain shared;
unknown or unavailable identities conservatively suppress cleanup. Ambiguous, foreign, outside, linked, unreadable or
missing references suppress optional cleanup without following them. Unknown or
linked task directories also suppress cleanup even if a glob would omit their
manifest. Ordinary non-strict task listing remains usable. Synthetic regressions
cover dot aliases, symlink aliases, linked/dangling directories and manifests,
malformed records, media/source-media references, real hard-link identities,
unknown identities and proven independent/unshared positive cases. Native Windows
short-name creation is not claimed from the POSIX run.
