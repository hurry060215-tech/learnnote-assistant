# Task ZIP serialization boundary (#143, 2026-10-09)

This independently reviewable increment moves the three existing task ZIP
serializers into `backend/app/task_archives.py`. It does not complete #143.
The final integrated baseline is concept tree
`fd35ac17cca6cb759aa193b6bd217262800688c7` (`ba9ea04`, including main
`7402d3f`, the concept changes and progressive-section newline correction).

## Ownership and compatibility

`main` retains route registration, the three handler names and signatures,
HTTP validation/errors, storage reads, report rendering, privacy projections,
annotation lookup, response headers and download filenames. No router factory,
dispatch registry, runtime context object or extra framework is introduced.

`StudyArchive` and `BundleArchive` explicitly carry the already-projected task,
literal note/transcript/visual/QA/claim contents and rendered bundle reports.
The three service functions return ZIP bytes. They own the member allowlists,
member order, encoding and compression. They never write source artifacts.
Optional personal annotations remain a separate schema-v2 member and are
omitted unless the caller explicitly supplies them, including an empty list.

Existing imports of `main.api_export_bundle`,
`main.api_export_sanitized_bundle` and `main.api_export_support_package` still
work. Their storage/read/render patch points are resolved in `main` on every
call. `main._write_file_if_exists` remains an alias and is explicitly passed
to the bundle serializer; `main.QA_HISTORY_FILE` remains configurable by
existing callers. The old incidental `main.BytesIO`, `main.ZipFile` and
`main.ZIP_DEFLATED` imports are implementation details, not retained aliases.

The serializers import only `models` from the application. The architecture
check rejects API, processor, downloader, storage or other application imports
from this module, including deferred imports. A fresh-process regression also
checks that importing it does not load the main app or storage layer.

## Byte, path and privacy contract

No task, artifact, annotation, QA or backup schema changes. No migration or
rebuild is needed. Source paths, download paths, subtitle/grid ZIP names,
missing-file skipping, existing failure propagation and recovery stay the
same. A failed export leaves source files and backups available for retry.
Reverting this code-only increment restores the earlier implementation.

Regular bundles preserve their existing full local diagnostic/task content.
Sanitized bundles retain the existing study-member allowlist, excluding raw
task records, diagnostics, media files and personal annotations. This refactor
does not claim arbitrary embedded study text is newly secret-free. Support
packages still receive the existing final sanitized reports and projected
events. There are no new network calls, permissions or dependencies.

`task_archives_v1.json` was captured before extraction. The final baseline
includes the three intentional concept routes; only the complete OpenAPI and
ordered-route digests changed during integration. The three archive route
schemas, TaskRecord schema and all six ZIP fixtures remain unchanged. The order
check now includes FastAPI’s lazily included routers. Six synthetic cases
cover ordinary/annotated bundles, generated subtitles, copied subtitle/grid
bytes, missing assets, QA and claims, sanitized variants, Unicode, CRLF and
support privacy. Regression checks compare every uncompressed member byte,
member order, compression method and response header, and confirm source files
and backups are unchanged. The fixture also freezes the three OpenAPI paths,
the complete OpenAPI digest, ordered public API operations and TaskRecord schema.
Intentional future API/schema changes must update that corresponding contract.

Local before/after comparison additionally established identical complete ZIP
bytes for all six cases with the ZIP clock frozen. Whole-ZIP hashes depend on
platform metadata/compressor versions, so cross-platform tests assert exact
member bytes and observable headers instead of freezing platform metadata.

## Measured production budgets

| Scope | Before | After | Enforced cap |
| --- | ---: | ---: | ---: |
| `main.py` | 4,762 | 4,702 | 4,800 → 4,705 |
| `task_archives.py` | 0 | 131 | 140 |
| Complete extracted backend group | 9,105 | 9,176 | 9,250, unchanged |

The monolith reduction is 60 lines. Total production code grows by 71 lines
because the explicit typed inputs and compatibility wiring are now counted.
The aggregate guard includes the new module; no budget is increased and the
existing CSS byte-order/aggregate guards remain intact.

Validation passed on the final integrated code: 965 backend tests under the
offline network guard; 154 script tests (three existing Windows/PowerShell
skips); the actual architecture checker, including Python/JavaScript cycles
and CSS budgets; compileall; and whitespace checks. An AST/raw-line check
confirmed that only the three handlers and relocated file-copy helper changed
in `main`; all 4,679 unchanged source lines retain their original line endings.

This change has no UI implementation. Cloud browser execution was not used;
actual Windows Edge acceptance remains a separate CI responsibility.
