# Claim-support evaluation

This is an offline scoring workflow for issue #129. It does not call a model,
read model credentials, download models, send sources, or change notes. It
measures agreement with supplied labels; it cannot establish that a course is
factually true.

## Three independent questions

1. **Literal source matching:** Does a complete source anchor match the
   note wording? Claim schema v7 preserves conditions and identifier punctuation.
   `direct` is still a literal-match category, not a general entailment result.
2. **Model opinion and attribution:** The existing explicitly confirmed chapter
   review can judge paraphrases. Its local parser checks schema and complete
   verbatim quotations. A quotation check does not establish that the model's
   semantic judgment is right. Results remain ephemeral opinions, not changes to
   the note, personal review record, or formal publication gate.
3. **Semantic quality:** Independently labeled supported, contradicted, and
   insufficient cases must be compared with the actual recorded model judgments.
   A model that labels everything insufficient must expose its lost paraphrase
   recall rather than pass by avoiding false support.

## Corpus and scope

`backend/tests/fixtures/claim_semantic_independent_20261016.json` contains original,
assistant-authored fictional examples, authored without inspecting the matcher or
older fixtures, then reviewed for ambiguous labels. It is not human-adjudicated
or representative real-course gold. It covers English/Chinese, paraphrases,
quantities and units, negation/conditions, causality, order, entity roles,
multi-source inference, and text descriptions of fictional visuals.

The visual-description cases test text entailment only. They do not validate
pixels, OCR, image models, or cross-modal grounding. Case rationales and decisive
source aliases remain in the scoring corpus and are excluded from request packets.

## Reproduce the local baseline

```sh
PYTHONPATH=backend python scripts/claim-semantic-benchmark.py \
  --literal-baseline --output build/claim-semantic-literal.json
```

Only literal matches become `supported` predictions in this diagnostic baseline.
Everything else is **unassessed**, not a predicted unsupported fact. Low semantic
recall is expected; do not rename this baseline a semantic evaluator. The older
public-source regression remains available as `scripts/claim-evidence-benchmark.py`.

## Prepare a separately authorized evaluation

```sh
PYTHONPATH=backend python scripts/claim-semantic-benchmark.py \
  --export-requests build/claim-semantic-requests.json \
  --output build/claim-semantic-not-run.json
```

This writes local files and exits 2 because no judgments were evaluated. The
packet contains the production system prompt, one claim and selected source text
per request, strict response schema, output-token limit, and SHA-256 input binding.
It contains no gold labels or rationales. Exporting it is not permission to send
it. A future live run requires an explicitly approved input set, provider/model,
credential setup, and request/cost budget. An entire corpus run is many requests,
not the single confirmed request used by the product's chapter review dialog.

Keep the corpus fixed before running. Record every attempted case, including
refusals and malformed or truncated responses. Do not silently retry failures,
repair outputs using the gold labels, tune to this set and call it held-out, or
replace missing judgments with gold answers.

## Recording format

A JSON file has exactly these top-level fields:

- `schema_version`: `1`
- `corpus_sha256`: copied from the exported packet
- `run`: `kind`, `model`, and `recorded_at` strings
  - `kind`: `recorded_model` for actual recorded outputs, or
    `synthetic_protocol_test` for fabricated protocol fixtures
  - Model name and timestamp are caller-supplied provenance, not independently
    authenticated by the scorer
- `results`: rows with `case_id`, `input_sha256` (from the corresponding request),
  and `response` (the unmodified chat-completions response JSON)

Never put keys, cookies, private request logs, or user course content into this
file. The bundled corpus needs none. The scorer does not send recording contents
anywhere. Unknown or duplicate case IDs, stale corpus/request fingerprints, and
extra top-level/run/row fields are rejected.

```sh
PYTHONPATH=backend python scripts/claim-semantic-benchmark.py \
  --recordings build/claim-semantic-recorded.json \
  --output build/claim-semantic-results.json
```

## Reading the result honestly

The report has overall, language, and risk-tag confusion matrices and
precision/recall for supported, unsupported (`contradicted` or `insufficient`),
contradicted, and insufficient. It also records coverage, missing responses,
protocol rejections, and whether the labeled decisive sources were cited.

- Missing/rejected answers are `unassessed`; recall includes them as misses.
- Precision is `null` if there were no predictions, never an invented perfect score.
- A correct verdict with missing decisive attribution remains visible as an
  attribution failure.
- Synthetic protocol outputs never demonstrate real-model accuracy.
- A completed report is `measured_fixture_only`, never an automatic acceptance
  pass; `general_semantic_quality_verified` remains false.
- Scores on this small fictional set cannot close the real-course or image-quality
  acceptance requirements. Use additional independent public/authorized course
  and pixel evidence, with human review, before claiming general semantic support.
