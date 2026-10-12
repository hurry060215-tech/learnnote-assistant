# Issue #143: media source context extraction

Snapshot base: `ba9ea04496431b3ee8e80bf2e9705fbc07c61dd1`.
Issue #143 remains open. This change extracts one downloader boundary; it does
not claim completion of the monolith reductions or native platform acceptance.

## Boundary and compatibility

`media_source_context.py` interprets explicit `ResourceCandidate` lists, page
URLs and captured request headers. It contains existing manifest inference and
enrichment, page/frame fallback ordering, allowlisted header projection,
page-scan trust classification and the call into candidate ranking. Outputs are
the original URL/header/container shapes and the existing candidate schema.

All 12 functions and six constants retain their pre-split ASTs. `downloader.py`
re-exports the same functions and constants with unchanged call signatures.
Fallback contexts retain the original candidate objects; inferred candidates
are deep copies. Candidate ranking retains its existing in-place kind/score
normalization and pairing behavior. No helper adds hidden runtime configuration,
clock, filesystem, network, subprocess or credential collection dependencies.

Empty or malformed source evidence keeps the existing empty result or fallback.
Fragment URL queries, sibling-manifest order, blob matching requirements,
header sanitation and third-party-frame filtering are unchanged. These helpers
do not grant permission to fetch a URL. Transport, redirects, SSRF checks,
Cookie filtering, replay limits, DRM checks, subtitle byte preservation and
failure recovery remain in their existing modules and call paths.

No API, task schema, source file, persisted artifact or migration changes.
There are no added packages, permissions, telemetry or network destinations.
Rollback is code-only and continues to read the same task and subtitle files.

## Budgets and evidence

- `downloader.py`: 2,757 -> 2,513 lines; ceiling 2,800 -> 2,520.
- `media_source_context.py`: 294 lines; ceiling 300.
- Extracted backend group: 9,105 -> 9,155 lines on the snapshot base; the existing
  9,250 ceiling is unchanged and explicitly includes the new helper.
- Pure imports are restricted to models, media kinds, candidate ranking and URL
  parsing. Guards reject deferred imports of API, processor, downloader,
  storage, transport and runtime; external imports are limited to pure standard
  library helpers. Fresh-process import checks enforce independent loading.

`backend/tests/fixtures/downloader_source_context_v1.json` was captured from the
pre-split downloader under `scripts/test-backend-offline.py`'s network guard,
using only synthetic `.example.test` candidates. It fixes full relevant candidate
fields, fallback object identity/order, input mutation, header precedence,
manifest query preservation, malformed URLs and trust decisions. The same
snapshot must pass through both the new module and downloader compatibility
exports. Independent edge tests cover deep-copy isolation, endpoint evidence,
missing hosts, label boundaries and empty inputs.

The baseline backend suite passed 962 tests before extraction. The final suite
passed 964 tests, including compatibility-export and independent-import checks.
Architecture passed; 157 script tests passed with three platform-only skips;
compilation and whitespace checks also passed. All backend verification
uses the offline runner with telemetry disabled and a task-local synthetic data
directory. Architecture, script tests, compilation and diff checks accompany it.
These checks do not establish Windows, macOS, real extension or live media gates.
