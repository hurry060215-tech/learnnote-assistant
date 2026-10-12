# Current filtered graph snapshots

This is one bounded increment of [issue #142](https://github.com/hurry060215-tech/learnnote-assistant/issues/142).
It exports and reconstructs the existing query-selected keyword cooccurrence
comparison. It does not build a semantic or global course graph, identify
agreement/conflict/causality, repair the live catalog, or recover missing source
files. Issue #142 remains open for those broader gaps.

## User flow

In a course, submit the comparison query and filters, then choose
**导出当前筛选关系图**. Unsubmitted form edits do not change this export's scope.
The JSON contains every result within the supported bounds, including complete
canonical source text. All canonical course evidence is retained to reconstruct
the current grouping choices accurately, including choices outside the filter.
The UI discloses that extra evidence scope. Treat the exported text as private
course content when choosing where to store or share the file.

The course list also offers **导入关系图快照（只读预览）**, including when the live
catalog is unavailable. Import checks the file and recomputes its graph in a
separate preview. Citation actions expand embedded text only. They do not
resolve live source files or make requests to their URLs. Reexport saves the
validated original snapshot. Existing group-history backup/restore remains a
separate operation.

The normal comparison returns at most 40 nodes, 100 matches and 100 edges. It
now reports total counts and explicit truncation flags. The drawing shows at
most 24 returned nodes; the separate list remains available. Snapshot graphs
are complete and their relationship list can be expanded in batches of 100.
The existing lexical search uses the first eight distinct case-folded terms;
the exact input and evaluated terms are both recorded, with a visible notice
when further terms were not evaluated.

## Version 1 contract

`format` is `learnnote.filtered-comparison`; `schema_version` is `1`.

- `course`: identity, revision, original title, paused state and ordered source
  references. The manifest does not contain absolute source paths.
- `sources`: ordered references, resolved source identities and canonical
  owners plus captured owner-revision fingerprints. Status is `ready`, `alias`, `missing`, `excluded`, `unindexed` or
  `unresolved_url`. Referenced IDs are partitioned into included, missing and
  excluded evidence IDs. A fingerprint and explicit redaction markers retain
  the distinction between the original reference and its safe projection.
  These statuses describe manifest/catalog/evidence records. They do not assert
  that an original media/source file still exists or matches the indexed text;
  this export does not read or hash original media/document files.
  Task owner revisions fingerprint only explicit source identity/version,
  source/type/mode/status and summary/review eligibility fields. They exclude
  model options, private connection settings, credentials and update timestamps.
- `scope`: exact submitted query, evaluated normalized terms and normalized
  source/type/time filters. Time filtering uses existing real numeric anchors
  or recorded timestamp locators. Untimed documents acquire no timestamps.
- `evidence`: full original canonical text, IDs, titles, source kinds, safe
  URI/locator, owner, course reference and recognized page/frame/time anchors.
  Registered video aliases resolve to their actual task owner; duplicate IDs,
  wrong-owner rows, generated notes and review drafts cannot supply relations.
- `history`: the exact validated split/merge history, including user labels.
  `group_state` reconstructs the latest groups for query and historical terms;
  `unresolved` explicitly distinguishes missing from changed evidence.
- `graph`: the complete deterministic cooccurrence result. Each edge names two
  distinct canonical evidence IDs and contains their citation titles/locators.
  `counts` and `truncated` describe returned completeness. `inference` is false:
  no model inference has taken place, and the relation is still only lexical
  cooccurrence, not a factual or verified semantic relationship.
- `limits`, `completeness`, `provenance`, `digest`: explicit resource bounds,
  scope and integrity metadata. There is no export timestamp, so unchanged
  inputs produce the same content digest.

Metadata is an allowlist: `start`, `end`, `frame_timestamp`, `page`,
`page_index`, `window_id`, `material_id`, recognized `kind` and a SHA-256
`source_revision`. Numbers must be finite, nonnegative and representable within
the browser's safe integer bound. HTTP(S) URIs lose userinfo, every query
parameter and fragments. Only application-owned `local://tasks/<id>` and
`local://materials/<id>` URIs survive. Filesystem/URL locators become explicitly
redacted unlocated anchors. Other metadata, including local paths and credential
fields, is omitted and recorded in `redacted_fields`. Source text, titles, user
labels and HTTP(S) URL paths remain exact; this projection does not claim to
scrub secrets a user has written into those retained fields.

`original_fingerprint` is the pre-redaction evidence fingerprint used by the
original grouping history. It is declared provenance, not an authenticity
proof. `snapshot_fingerprint` covers the complete portable record, and `digest`
covers the complete snapshot except the digest itself. Hashing sorts object
keys, uses UTF-8 JSON without insignificant spacing, and normalizes integral
floating-point numbers to integers so browser JSON round trips remain stable.
Imported fingerprints and source claims remain untrusted even when all checks
pass. The preview says so explicitly.

## Resource and storage boundaries

Exports reject rather than silently truncate when they exceed 20,000,000 UTF-8
JSON bytes, 200 source references, 10,000 candidate evidence IDs, or 20,000
relations. Group reconstruction also rejects more than 100,000,000 bytes of
text multiplied by distinct query/history terms. Existing grouping-history
limits still apply. Reducing the course reduces retained evidence; narrowing
query terms can reduce graph and grouping work. Source/time filters alone do
not reduce the retained grouping evidence. An oversized history can still use
the existing separate history backup.

GET `/api/courses/{id}/graph-snapshot` requires the course revision plus the
comparison query and filters. It reads the catalog in a single SQLite
`mode=ro` transaction and reads episode bindings without initializing schemas.
An absent or corrupt catalog fails explicitly. No export repairs an index or
creates a replacement database. The persistent database, WAL content, original
files, courses and history remain unchanged. For an existing WAL-mode catalog,
SQLite may create or update its transient `-shm` reader coordination file;
`mode=ro` does not promise zero filesystem bookkeeping. This implementation
does not use `immutable=1` or ignore committed WAL contents. Course/history edits, changed episode
resolution or changes to the specific task manifests read for this capture
invalidate the export; no full-library lock is acquired.

POST `/api/courses/graph-snapshot/preview` accepts `{ "snapshot": ... }` with
a bounded streaming request body. It rejects unknown or inconsistent schema,
duplicate JSON keys/evidence IDs, unsafe metadata, contradictory owners,
unsupported relation claims, altered digests or graph payloads. It recomputes
groups, unresolved references and every edge from the portable records, then
compares the complete normalized result. It does not read SQLite, the course
manifest, live evidence, source files or grouping history, and performs no
writes. The browser preserves the raw file JSON inside this wrapper so duplicate
keys cannot disappear before validation. This is snapshot reconstruction, not database restoration.

## Validation

Synthetic offline backend tests cover mixed video/document/page/frame anchors,
all filters, exact split/merge history, missing and stale records, generated and
review exclusions, wrong owners and aliases, deterministic JavaScript numeric
round trips, 45 sources / 135 citations / 990 edges, explicit resource rejection,
tampering with recomputed digests, and absent/corrupt databases with before/after
file hashes. DOM tests cover repeated actions, stale responses, cancellation,
close/navigation, literal hostile content, read-only embedded citation actions
and readable limits. The Windows Edge fixture exercises actual export/import
endpoints after deleting its synthetic original course and sources. Actual Edge
execution is a separate CI check; node tests do not establish browser acceptance.
