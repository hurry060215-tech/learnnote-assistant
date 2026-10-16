# Claim support and chapter-review audit, 2026-10-16

Baseline: `b590e55`. Scope: issue #129's remaining support boundary and audit of
#151. No provider credentials, private course data, paid calls, or live model
responses were used.

## Implemented

- Claim schema v7 uses complete anchors for literal matches.
  It no longer separates at commas/semicolons, which could discard a condition,
  attribution, negation, unit, or exception. Ambiguous ASCII sentence punctuation
  remains in the complete anchor. Cross-sentence denial/attribution stays intact.
  Question punctuation, case, word boundaries, underscores, quotations,
  and brackets are preserved. Only edge citations in note prose are removable.
- Read projections of old/unknown schemas clear stale direct verdicts and reset
  counts. Candidate navigation is retained and the map requires a current rebuild.
  This is an in-memory projection: source note files, raw maps, personal notes,
  existing archive files, and backups are not rewritten. Newly generated ZIPs
  intentionally contain the downgraded legacy verdicts rather than unsafe old
  direct labels; explicit v7-export fixtures cover only this changed member and
  ZIP length, while every other archive byte remains frozen. The browser accepts schema v7 and
  refuses old maps as current source-span bindings.
- Chapter-review source budgeting interleaves candidate ranks across claims and
  admits whole adjacent-context groups. It cannot keep a positive cue by silently
  discarding its adjacent negative/qualified cue just to fit the budget. Selected
  text stays in original order; aliases are deterministic. Coverage discloses
  complete-context candidate counts per claim and truncation. No extra source
  requests, model calls, retries, or automatic next batches were introduced.
- Added an independent bilingual synthetic corpus and an offline recorded-response
  scorer. Gold labels are separate from exported provider inputs. Missing,
  malformed, truncated, or misattributed responses cannot become a false semantic
  pass. See [evaluation instructions](../CLAIM_SEMANTIC_EVALUATION.md).

## #151 audit

The baseline already provides source/attempt/note/section/model-bound chapter
status and manually confirmed semantic review. Limits remain 12 claims, 12,000
source characters, 6,000 claim characters, 2,000 output tokens, 30 seconds, one
request, no automatic retry, and fresh per-batch consent. Semantic opinions remain
separate from literal matches and do not alter publication/personal review state.
No replacement of that implementation was necessary.

The relevant existing regressions cover monotonic events/replay, progressive
chapters, non-streaming fallbacks, draft labels, scoped source binding, retry and
cancel invalidation, late/stale response suppression, hidden-page behavior,
reader/selection stability, and HTML-safe dynamic rendering. This audit does not
repeat or replace earlier two-hour SSE observations or native-platform gates.

## Verification and remaining limits

- Independent code review caught and fixed a question-to-statement match,
  cross-sentence denial loss, and fractional/string schema acceptance. Final
  independent review found no remaining blocker in the reviewed matching,
  source-budgeting, and scoring changes.
- All 72 web test files pass; script suite: 203 tests, 3 expected skips. Python
  compileall and git whitespace checks pass. Full offline backend suite: 1,700
  tests pass with 20 expected environment/optional-dependency skips (138.9s).
- Existing 60-case public-source regression: no false direct support, direct
  precision 1.0 / recall 0.5, review-gate recall 1.0. This unchanged regression
  is still a fixed-corpus matching test, not general semantic quality.
- New independent set: 80 cases, 40 English/40 Chinese, 40 supported nonliteral
  paraphrases/20 contradicted/20 insufficient. The literal diagnostic abstains
  on all 80, with supported recall 0/40, unsupported-detection recall 0/40, and
  undefined precision (no predictions). Abstention does not count as correct
  unsupported detection. No actual model judgments were evaluated: model status
  is `not_run`. The result is evidence of the remaining gap, not a semantic pass.
- Raw archive fixture is unchanged. Explicit new expected export projections
  cover v6 downgrades; source map, personal annotation, note, event and backup
  bytes remain unchanged. All other ZIP members keep their original exact bytes.

The actual-browser command remains:

```sh
LEARNNOTE_ACCEPTANCE_BROWSER=/path/to/installed/chromium \
LEARNNOTE_ACCEPTANCE_PYTHON=/path/to/test/python \
node scripts/section-review-acceptance.cjs build/section-review-ui
```

The local installed Chromium could not launch because the execution sandbox
rejects its process socket. The supported escalated launch failed before running
inside the environment wrapper. No local screenshots or visual pass are claimed.
The unchanged gate should run in the project's hosted UI acceptance environment;
it captures both themes at 1280/1440/768/390px (65 PNGs), completed and progressive chapter-review
states, and checks exact consent payloads, stale/reopened dialogs, artifact bytes,
next-batch confirmation, and absence of external requests. Windows/Edge remains
its own platform acceptance, not inferred from Chromium.

General semantic paraphrase recall and cross-modal pixel quality remain **open**.
The model review path exists, but synthetic protocol responses and the literal
baseline do not prove real-model semantic performance. Completion requires an
explicitly authorized evaluated provider/model/input set and independent real
course/pixel adjudication. This change does not silently promote model judgments
or relax the final evidence gate to manufacture that completion.
