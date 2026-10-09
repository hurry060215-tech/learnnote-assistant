# Course-scoped questions: #157 criterion 6

The default reader can now open **笔记工具 → 课程与提问**, select a
course, and choose **在课程中提问**. The question form has an explicit course
selector and refresh control. It returns matching local original excerpts with
buttons to inspect each canonical source. Course keyword comparison and the
single-material assistant remain separate existing features.

This completes the missing question-scope implementation, not a claim that
keyword retrieval semantically answers arbitrary questions. The visible copy
calls the output local excerpts and explicitly discloses no model synthesis.

## Server contract

`POST /api/courses/{course_id}/ask` accepts a nonblank `question` (up to 2,000
characters), required current `revision`, optional `limit` (1–50, default 6),
and `mode` (default `lexical`). Unknown fields, including client-supplied
evidence IDs, are rejected. The server resolves current course membership
itself from task, material and bound URL-episode sources.

- A temporary SQLite membership table restricts every FTS and LIKE query before
  ranking and limits. IDs are not truncated to the first UI page. The projection
  text fetch stays bounded to 50 lexical or 500 optional reranking candidates.
  Registered video materials resolve the current linked task projection rather
  than their older first-500 registration snapshot.
- Generated notes, community records and draft summaries cannot supply course
  answers. Review-required row metadata and the current task owner's review/
  transcript-draft state also exclude legacy projections without flags, even
  through registered video materials. Deleted sources/evidence are excluded.
- An empty course or no matching original evidence returns `grounded: false`,
  empty citations/results and an explicit course-specific no-answer message.
  There is no fallback to global matches.
- The response identifies the course ID, title and revision. Stale revisions
  return 409; unavailable/deleted courses return 404. In-process course edits
  and deletion share the membership lock. This does not claim a distributed
  or multi-process consistency protocol.
- Citation IDs, source kind/ID, title, locator, URI, and existing start/end
  timestamps remain canonical. Source buttons use the reader's existing
  evidence navigation.
- Optional `embedding`, `semantic` and `local-embedding` modes only rerank the
  bounded scoped lexical candidates. Course requests require cache-only model
  loading, with no download or remote-model fallback. Missing package/cache
  returns a fixed actionable 409. The default form never invokes a model.

No persistent schema migration, source-file mutation, permission change,
credential, paid API, or new dependency is introduced. Existing global search
and single-source question behavior is preserved. Optional semantic results do
not establish semantic verification or exhaustive course-wide similarity.

## Synthetic verification

| Contract | Verification |
| --- | --- |
| Matching outside-course documents cannot starve in-course evidence | `test_course_questions.py`: FTS and LIKE, 80 higher/newer external matches, limit 1 |
| Long courses retain late evidence IDs | 1,200 canonical anchors, only the final anchor matches, through both task and registered-material membership |
| No-evidence, stale/deleted/missing scopes fail closed | Empty course, only external matches, source deletion, orphan task projection, removed evidence, stale revision, invalid course and request fields |
| Canonical evidence only and exact source anchors | Generated-note/community/draft/review flag and legacy owner-state exclusion; document source and video 31–45-second citation |
| Optional semantic scope and local boundary | 520 member + 650 external anchors; reranker sees only 500 members; cache-only constructor and missing/invalid-cache 409, with offline guard |
| Duplicate and stale UI results | `web/tests/course_question.test.mjs`: repeated submission, scope/revision mismatch, late course loads, 404/409 recovery, dismissal and reader navigation |
| Actual default-reader rendering | `scripts/course-question-acceptance.cjs`: intercepted synthetic Windows Edge fixture, invoked by `ui-visual.yml`, with report and screenshots |

Backend tests run through `scripts/test-backend-offline.py`, which blocks
external DNS/HTTP/socket/model-fetch paths. Semantic tests use synthetic local
doubles; they do not download or run a real embedding model. The package is
optional and absent in the cloud test environment. Cache-only argument support
is present in the declared minimum [Sentence Transformers 3.0.0 source](https://github.com/UKPLab/sentence-transformers/blob/v3.0.0/sentence_transformers/SentenceTransformer.py)
and [current official API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html).

The Linux cloud task does not run Windows Edge. Exact-head browser CI is the
remaining browser-verification step; passing Node controller tests or fixture
syntax alone is not reported as browser acceptance.
