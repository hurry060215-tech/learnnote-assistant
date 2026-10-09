# Course-local concept grouping and canonical comparisons

Related: [#142](https://github.com/hurry060215-tech/learnnote-assistant/issues/142)
and [#263](https://github.com/hurry060215-tech/learnnote-assistant/issues/263).

The existing course comparison could connect the word “scale” in a musical
lesson to “scale” in a weighing lesson. Users can now select cited occurrences
and split them into named groups, or merge selected groups. These are explicitly
personal organizational choices, not verified semantic equivalence. The source
graph and list remain the existing small SVG/list implementation.

Every emitted edge still means only keyword co-occurrence. It has two distinct,
canonical evidence IDs and their actual titles and locators, with direct source
actions in the list. Splitting a homonym suppresses cross-group edges. No model
is called and no causal, consensus, contradiction or factual claim is generated.
The view labels the actual relation kind, uses dashed keyword edges, and treats
unknown relation kinds as unknown rather than inventing a factual label.

## Persistence and recovery

- User choices live outside the rebuildable SQLite index, under the configured
  data directory. They contain references/fingerprints and exact user labels;
  no source, note edition, personal annotation or course manifest is rewritten.
- A revisioned, append-only event history is saved atomically. Before replacing
  the current file, the complete previous snapshot is retained in its history
  directory. Retries reuse a request ID; conflicting reuse or stale course,
  evidence-scope or grouping revisions are rejected without writing.
- History reads bind file type, size and a capped byte read to one descriptor.
  Compact JSON makes the byte limit identical across Windows/Linux line endings.
  Unknown exceptions return fixed public codes, never arbitrary exception text.
- IDs are resolved server-side within current, canonical course membership.
  The fingerprint covers original text and canonical source/locator metadata.
  Missing or changed references stay in the history and appear as unresolved;
  they cannot contribute a relation or be silently included in a merge.
  Rebuilding identical original evidence resolves its existing reference again.
- JSON export includes the complete history. Restore accepts an identical
  history, an older prefix (no-op), or a continuation of the current history.
  Divergent histories and malformed data are rejected. Older exports never
  overwrite later local edits. The backup applies only to its original course.
  Downloads use the configured backend API. Locale switching preserves exact
  group labels, search terms, titles and excerpts, including combining characters
  and literal newlines in saved labels.
- Damaged identity files are preserved and fail closed; they are never silently
  reset. Recovery of such a file requires preserving/moving it aside and using
  a valid snapshot. The UI does not claim to repair arbitrary user-history
  corruption. This is separate from rebuilding the disposable evidence index.
- Explicit bounds: 1,000 referenced occurrences per operation, 1,000 operations
  and 20 MB per course history, and 100,000 scoped IDs per comparison. Reaching
  a bound fails visibly instead of truncating saved choices.

## Canonical evidence bug #263

The old comparison helper excluded only `metadata.kind=note/community`.
Synthetic rows tagged `generated-note`, `review-draft` and `transcript-draft`
were returned as original source matches. The course-question endpoint already
excluded them. Old rows also remained eligible after their owner became a
review-required draft.

Comparison now reuses the verified course membership/owner checks and rejects
generated, community, draft and review-required rows. Complete scoped IDs are
resolved in batches of at most 500: an excluded first page cannot hide a later
canonical source. Registered video aliases use the verified owner's current
IDs, including citations added after registration, and cannot duplicate an edge
or expand membership to another task. Video aliases obey the video filter.

Real-handler tests cover the five #263 criteria, including 510 invalid rows
ahead of a valid citation, legacy owner changes, aliases and foreign IDs.

## Original #142 acceptance audit

| Criterion | Evidence and remaining limit |
| --- | --- |
| Every edge has at least two source references | Enforced for emitted co-occurrence edges; canonical source filtering strengthened for #263. |
| Course/video/time/source-type filters | Existing course, source, task/material and timestamp filters retained; registered videos remain video sources. |
| Same-name concepts can split/merge | Implemented as course-local, per-keyword occurrence groups. No global normalized concept/entity system is claimed. |
| Inferred and factual edges visually distinct | Co-occurrence and inferred/unknown kinds are truthfully labelled. There is still no source-supported factual relationship producer, general inference/fact model or consensus/conflict view. |
| Damaged index can rebuild locally | Real task-index and document-source rebuild regressions preserve grouping histories and identical evidence IDs. Missing/changed citations stay unresolved. No complete global concept-index recovery system is claimed. |
| Answers name videos and time points | Comparison excerpts and edge citations contain original title/locator and clickable evidence IDs; existing scoped-question tests stay green. |

**Keep #142 open.** This increment does not supply global concept normalization,
semantic relation assertions, a consensus/conflict view, or a complete offline
graph export. Its JSON export is the lossless course grouping history.

## Validation

- Final validation combines main `519d8afeaabb8b323e223b33ddb669143f979ad9`
  and progressive draft correction `2cea5f5cd97fae0acae96a4bed6e9279b592f2a9`.
- Offline backend suite: **957 tests passed** on the combined implementation.
  This includes real handlers, source eligibility, identity history, file
  replacement/growth, fixed public errors and Windows-stable history bytes.
- Web tests: **47 executed files, 116 Node-reported entries passed**, including repeated submission, uncertain retry, stale
  responses after Close/newer navigation, relation-kind labels and backup input.
- Script contracts: **154 run: 151 passed, three environment skips**. Release
  auditing rejects a bundle missing the new course concept module.
- Architecture/import/size guards pass without increasing budgets. Syntax and
  the study-product fixture self-test pass.
- The new Windows Edge fixture is wired into the existing actual-backend
  study-product visual run. It covers split/reopen/merge, restoring an older
  history, complete JSON download, missing/rebuilt citations, exact document
  navigation, and 390/1024 px light/dark captures with a long group label.
  **It was not executed in this cloud workspace.** Browser
  validation and screenshots must come from the authorized Windows CI run.

All tests and browser fixtures use synthetic local sources. No external model,
website, account, permission, security setting or browser session was used.
