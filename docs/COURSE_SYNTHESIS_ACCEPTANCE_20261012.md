# One-call course synthesis: bounded slice of #138

The existing course `/ask` route and default “在课程中查找” action remain local
excerpt retrieval with zero model calls. A separate “AI 综合（先预览与确认）”
action opens a review and consent flow. It does not write notes, course files,
evidence, credentials, or chat history.

## Explicit boundary

- `POST /api/courses/{id}/synthesis/preview`: strict `question`, `revision`,
  `mode` (`question` or `summary`), `base_url`, and `model` fields. It reads local
  evidence and the exact saved selection. No raw keys/options or provider calls.
- `POST /api/courses/{id}/synthesis/answer`: strict `preview_id`, `fingerprint`,
  and `share_source: true`. Consent is bound to that preview's course, question,
  evidence/owner state and selected connection. Both source and selection are
  checked before the request and before publishing the result.
- Preview tokens expire after ten minutes and are consumed before an attempt.
  Reusing a token after success, failure, timeout, or while pending fails closed.
  A process restart invalidates tokens. The bounded in-memory store persists no
  source text or credentials. Only one request per course can be in flight.
- The selected endpoint/model must match saved settings. Missing credentials do
  not use defaults, environment credentials or an earlier provider. The SDK gets
  `max_retries=0`; redirects and environment proxies are disabled. No probe,
  fallback, repair, or second model request occurs.
- At most six canonical anchors and 24,000 source characters leave the service.
  The requested output limit is 3,000 tokens. An asynchronous 30-second provider-wait
  deadline does not cancel remote computation or charges. Local validation and
  usage recording can take additional time; ledger writes run off the event loop. These limits
  are not a monetary cap; the UI explicitly reports unknown monetary cost and
  warns that a local gateway may forward data.

## Evidence and claims

Membership and current canonical owner checks precede selection. Generated,
review-required, deleted, mismatched, and invalid-time evidence is excluded.
The local read scan stops at 10,000 rows across at most 200 course members,
using the existing task index without sorting the entire catalog first. Metadata
is bounded to 16,384 characters and 16 nesting levels; malformed/duplicate keys
are excluded. Any individual original anchor over 24,000 characters refuses
synthesis instead of searching a truncated prefix as if complete. An
incomplete scan refuses synthesis, labels totals/coverage unknown, and reports
unscanned members. It never uses a partial scan to claim complete coverage.

Question mode selects up to six lexical matches using the existing tokenizer
and literal fallback. Summary mode requires every eligible indexed member anchor
to fit the six-anchor/24,000-character bounds; overflow refuses synthesis rather
than sampling. Missing, excluded, and unindexed members remain visible. A summary
is only about available indexed evidence, not the entire underlying course.

Server-owned `E1` aliases bind original evidence and canonical task/material
owners. Video citations retain finite original times and actual course episode
IDs when present. A registered video without a real course episode has an empty
episode list and canonical task/member references. Documents get no episode IDs.
Only the redacted question and `{source_id, text}` evidence fields are sent to the
provider; paths, source URLs, history, task options and canonical owner metadata
are not provider fields.

The one `submit_course_answer` response must be either insufficient evidence or
bounded claims with source aliases and literal complete-anchor or Chinese
sentence support quotes. ASCII punctuation is not split because abbreviations,
initials and code operators can otherwise discard a preceding qualifier.
Unknown aliases, fragments that remove negation, malformed/extra fields,
multiple tools, incomplete output and invented direct quotes are rejected.
Summary answers must cite every selected alias. This is structural attribution
and citation coverage, not semantic completeness or truth verification. Every
paraphrase remains “AI 综合 · 待核对”; only a claim exactly equal to one original
support sentence can be displayed as a direct quote. Links and timestamps are
constructed locally. No confidence scores or `grounded: true` claim is added.

## Validation and limits of this evidence

Integrated on `acebfa6`: 1,553 offline backend tests, 138 JavaScript test files,
178 script tests (three existing skips), and 28 desktop launcher tests passed.
An independent review and 32 focused synthesis contracts also passed, including
connection/source races, bounded SQL work, corrupt metadata, NUL truncation,
conservative quote boundaries and nonblocking usage recording. The two OpenAPI fingerprint fields were updated for the two new routes; TaskRecord
schema and the archived ZIP member bytes remain unchanged. Actual Edge acceptance
is a separate required gate below, not implied by these local checks.

`backend/tests/test_course_synthesis.py` uses synthetic local files and a mocked
structured provider. It includes real loopback HTTP handlers for the API and
SDK, source-disk hash invariants, no-call paths, server duplicate protection,
source/route races, a stalled HTTP response deadline, redirects/errors,
actual-or-unknown usage and adversarial tool output. It is not live model quality,
provider compatibility, billing or cost validation.

`web/tests/course_synthesis.test.mjs` covers consent, literal text rendering,
source navigation, repeated submission, question/course/model changes,
close/reopen, Escape and reader navigation. Existing local question tests remain.

`scripts/course-question-acceptance.cjs` extends the existing Microsoft Edge
Windows CI gate with explicit synthesis preview/confirmation, source navigation,
escaped generated text, duplicate and stale-route protection, and a 390px preview
containing a 2,500-character unbroken string. The consent and final button must
remain reachable with no horizontal page overflow. Screenshots 07–09 and the
report are collected in the existing `course-question-ui` artifact. An additional
16 viewport captures show the form and final consent at 1280/1440/768/390px,
each in light and dark themes, with symmetric dialog gutters and reachable
controls. This visual pass invokes local previews only, without another answer
request. This script
uses intercepted synthetic API/model responses; it does not test a real model.
Actual Edge screenshots must be inspected in CI; they were not run in this Linux
workspace, where no shared Playwright runtime is available.
