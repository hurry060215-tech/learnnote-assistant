# Local cited relation candidates

Status: bounded local backend and graph/list UI delivery for #142. Issue closure
still depends on the concrete acceptance checks below. Existing keyword
comparisons and version-1/2 comparison snapshots retain their original behavior.

## Read-only API

`GET /api/concept-relations` captures the current **indexed** local library.
It includes indexed tasks and owned document materials even when they are not in
any course. It does not crawl pages, run a model, download embeddings, initialize
or repair SQLite, or save a second authoritative graph database.

Optional parameters:

- `course_id` and its current `revision`: restrict to a selected course and honor
  its split/merge history. A stale revision is rejected. Course grouping choices
  are deliberately not applied to unrelated library sources.
- `q`: a case/spacing-normalized literal phrase, up to 200 characters; empty means
  all supported assertions. This is not a synonym search.
- `source_id`: keep relations involving the selected canonical source, retaining
  their counterpart citations. Every returned relation still has at least two
  distinct canonical sources. A selected third source is included in the chosen
  positive/negative pair; known aliases never count as independent support.
- `source_kind` (`task` or `material`), `start`, `end`: restrict **all** evidence
  contributing to a relation by type and overlapping video seconds. Document
  anchors with no video times do not enter a time-filtered result. Combining these
  filters can legitimately leave fewer than two sources and therefore no edge.

The response is the complete bounded `learnnote.cited-relations` version-2 JSON
snapshot. It includes `scope`, source eligibility/missing counts, portable original
evidence, course grouping history, graph, and an integrity digest. Saving this
response provides an offline export. `POST /api/concept-relations/preview` accepts
`{"snapshot": <that response>}` and strictly reconstructs the graph from its
embedded evidence without consulting or changing the local catalog. Imported
source identities and content remain unverified even when all digests match.

Version 1 imports retain the original evidence-first `source_id` semantics and
their exact graph, digest, and re-exported snapshot data. Those old single-source
exports contain no cross-source edges. The preview displays this limitation
without upgrading or consulting live data. Generate a fresh version-2 snapshot
from local sources to use incident-relation filtering. The type/time/query and
course-identity rules are unchanged; the graph's evidence count is the eligible
construction scope, including counterpart evidence, not just the selected source.

The Courses catalog now offers a whole-library cited-relation view; each course
also offers a scoped view. Generation is explicit. Filters include literal query,
canonical source ID/type and video time. Solid source-occurrence and dashed
inference edges have matching text labels and a paginated list fallback. Node
buttons filter by literal spelling; citation buttons open canonical live evidence.
Snapshot imports only expand embedded original text, never resolve imported IDs
against live records. Import is available before a catalog response, and both
failed validation and changed filters remove stale previews. A hosted actual-Edge
gate covers the new UI; a workflow definition alone is not a screenshot pass.

## What is normalized and generated

Concept labels preserve their source spellings. NFC Unicode normalization,
whitespace normalization, and case folding provide stable lexical IDs. There is
no compatibility-character folding, translation, synonym merge, entity linking,
coreference resolution, or claim that two equal labels mean the same thing.
Existing course-level same-name split/merge decisions take precedence; changed
or missing referenced evidence cannot silently rejoin a group.

The parser supports a deliberately narrow set of simple English and Chinese
relation sentences, such as “Gradient descent requires gradients.” and
“梯度下降需要梯度。”. It rejects question/exclamation endings, quotation syntax,
comma/semicolon compounds, common hedges/conditions/attribution/negation outside
the recognized predicate, and sentences embedded in a multi-sentence line.
Both relation kinds require each selected evidence record to consist of its whole
standalone sentence; surrounding denial, attribution, or conditions are never
discarded to create a relation. Unrecognized language is unclassified, not false.
This is not general NLP.

Every emitted relation has at least two unique evidence IDs and distinct known
canonical sources. Registered task aliases, repeated segments, same media hashes,
and known shared page identities cannot manufacture a second source. Distinct
sources still do not establish independent authorship or independent corroboration.
Page identity uses the existing sanitized URI/query policy; generalized URL aliases,
redirects, mirrors, and unknown copies are not proven equivalent. Equal normalized
labels likewise do not prove the same meaning.

- `kind: source_assertion`, `relation: same_quoted_assertion`: at least two sources
  contain the same complete quoted sentence after the disclosed spelling
  normalization. This establishes **quote occurrence only**, not fact correctness,
  causality, semantic equivalence, or consensus. `truth_verified` is always false.
- `kind: inferred`, `relation: possible_negation_difference`: two different sources
  contain a recognized positive/negative form with matching lexical endpoints and
  predicate. Both selected evidence records must consist of their standalone
  sentence. This is a review candidate, not an established contradiction. Outside
  context, scope, speaker identity, and homonyms can still change interpretation.

All citations retain the exact quote, Python Unicode-codepoint offsets into the
embedded original text, source title/type, stable source owner, locator, sanitized
URI, and available time/page/frame anchors. Do not interpret offsets as JavaScript
UTF-16 indexes. Full source evidence remains in the snapshot so context can be
inspected. No graph answer should omit these source titles and locators.

## Freshness, reconstruction, and limits

The graph is derived afresh from a consistent read-only SQLite transaction and
rechecked task/course/history revisions. Incremental source edits therefore appear
on explicit regeneration without retaining stale derived relations. A concurrent
change is rejected with a reload-required result. There is no persistent relation
index to corrupt. A missing or damaged underlying evidence catalog returns a clear
error; the existing explicit task index rebuild / library recovery workflows are
still required and are never invoked by a graph read.

Current fail-closed limits: 1,000 sources, 10,000 evidence rows, 24,000 characters
per evidence row, 2,000,000 source characters, 10,000 relations, and 20 MB serialized
snapshot. Oversized scans return HTTP 413 rather than an incomplete graph. Use an
explicit smaller course if the library exceeds these limits. Eligibility and
supported-grammar coverage are distinct from source completeness.

Exports use the existing graph redaction policy: remove URI credentials/query/
fragment, path-like locators and non-allowlisted metadata. Titles, source text and
HTTP(S) URL paths remain literal and are not automatically scrubbed for secrets.
Review before sharing outside the machine.

## Remaining acceptance for #142

- Re-run the hosted real-browser acceptance on the final source-filter change:
  selecting one source must retain cited counterpart relations, and old version-1
  snapshots must remain read-only and re-export unchanged.
- The underlying task index can be rebuilt when missing, but a corrupt catalog
  is currently blocked by the ordinary rebuild action. Existing document-catalog
  recovery requires a suitable metadata snapshot. A safe explicit task-only
  corruption recovery route without a prior catalog snapshot remains separate work.
- Existing grouping history remains reversible through its established workflow;
  the new derived graph itself has no mutation/undo operation. Offline snapshot
  preview never restores or overwrites a course or its history.

General synonym resolution, autonomous homonym disambiguation and universal
semantic consensus/conflict accuracy are not implemented. They are limitations
of this intentionally bounded feature, not extra original acceptance criteria:
the issue explicitly permits same-name meanings to be split/merged by the user.
Current tests establish attribution, abstention, deduplication and filtering, not
general semantic correctness. A future broader semantic engine would need its
own independent quality evaluation and explicit authorization for external models.
