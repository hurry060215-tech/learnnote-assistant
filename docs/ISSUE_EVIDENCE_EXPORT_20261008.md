# Evidence, Unicode, semantic notes and export acceptance

Date: 2026-10-08. Related: [#129](https://github.com/hurry060215-tech/learnnote-assistant/issues/129), [#150](https://github.com/hurry060215-tech/learnnote-assistant/issues/150), [#152](https://github.com/hurry060215-tech/learnnote-assistant/issues/152), [#156](https://github.com/hurry060215-tech/learnnote-assistant/issues/156).

## Result and tested revision

This followthrough fixes reproducible publication, Unicode propagation, nested-formatting and export-panel gaps. **#152 is a closure candidate against its original bounded-parser acceptance scope after CI/review. #129, #150 and #156 retain the specific gaps below.** WPS and unrestricted LaTeX are historical extra checks, not requirements named in the original issues. This report does not close issues.

- Tested code: `1fc5511085ec327b6a513de913ed795bd5e46ce6`, incorporating privacy baseline `01e10aa99ce56e6b769a95f992efd4e9bcd6f5e0` (#230).
- Followthrough commits: `0c5eac9` panel/presets, `8916d8e` Unicode/Notion, `3b8efec` publication/structure. The first increment was merged in #224; its earlier test counts are historical, not current proof.
- Linux cloud, Python 3.12.14, ReportLab 5.0.1, python-docx 1.2.0, pypdf 6.19.0, Pillow 12.3.0, charset-normalizer 3.5.2. DOCX rendering used local LibreOfficeDev 26.8.0.0.alpha0 and Poppler.
- Synthetic fixtures and the existing recorded public-source corpus only. No paid model, account change, remote document conversion or Notion send. Native processes launched with both telemetry opt-outs before initialization. Earlier blocked runs are excluded.

## Current regression evidence

| Check | Accepted result |
| --- | --- |
| Full offline backend | **747 passed, no skips**, 81.297 s |
| Scripts discovery | **117 tests, pass, 3 platform skips**, 2.805 s |
| Desktop discovery | **28 passed**, 0.166 s |
| Export panel runtime DOM | **11 passed** |
| Obsidian `npm run verify` | **10 passed**, TypeScript and production bundle pass; Moment remains host-provided |
| Actual TypeScript Obsidian importer/backend ZIP/in-memory vault | **10 checks passed**, no network |
| Architecture, compileall, i18n, Markdown renderer, diff whitespace | All pass; 22 boundary modules, 10 routers, 2 state modules, 21 size guards; extension 263 keys per locale / 241 referenced |

```sh
export ORT_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_TELEMETRY=1
export PYTHONPATH=backend:.
python scripts/test-backend-offline.py
python -m unittest discover -s scripts/tests -p 'test_*.py'
python -m unittest discover -s desktop/tests -p 'test_*.py'
node web/tests/export_panel_behavior.test.mjs
node web/tests/markdown_render.test.mjs
npm --prefix integrations/obsidian-learnnote run verify
python scripts/claim-evidence-benchmark.py --output build/claim-report.json
python scripts/export-long-document-qa.py --output-dir build/export-qa \
  --template academic --include-keyframes
```

New focused suites: `test_unicode_export_matrix.py`, `test_transcript_publication_quality.py`, `test_nested_note_exports.py`, `test_page_text_note_contract.py`, and expanded `test_export_preset_routes.py`. They run within the full guarded backend suite. Cloud browser localhost access was unavailable. Panel tests execute real JavaScript against DOM/fetch mocks; they do not claim native browser visual acceptance.

## #129 Claim-level evidence

| Original criterion | Current result |
| --- | --- |
| Chinese entities/numbers/causes/steps/visual descriptions enter the gate | Bilingual fixtures and 60-case benchmark run. Extraction remains a restricted prose projection, not exhaustive factual table/quotation extraction. |
| Every fact has timed/visual evidence | Direct claims retain stable evidence IDs/locators; documents retain document locators. Unmatched/merely located statements explicitly require review. Timestamps are not semantic proof. |
| Click claim to open subtitle/frame | API/source-range contracts pass; no current production-task browser click-through evidence here. |
| Unsupported facts cannot silently enter formal notes | Video, saved/subtitle-only and now **page-text** use visible review markers and final-map rebuild. Verbatim evidence, source-only/empty notes and review-action prompts avoid spurious warnings. |
| Stable Markdown/Obsidian/bundle references | v6 IDs use task/text/occurrence and Unicode-codepoint spans. The actual Obsidian importer now retains and links `claim_evidence_map.json`; ZIP/import/re-import preserves the ID. Old maps request rebuild. |
| Legitimate paraphrases not broadly rejected | Content is retained for review; automatic direct-support recall remains insufficient for complete semantic verification. |

Current fixed corpus: **60 cases, EN30/ZH30, 12 sources**. Direct precision **1.00**, recall **0.50**, false direct support **0**; review precision **0.75**, recall **1.00**. Twelve supported paraphrases are downgraded. These are fixed-corpus classification metrics, not general factual accuracy. **Keep #129 open** for semantic support/extraction and real claim-to-source UI acceptance.

## #150 Unicode and publication

| Original criterion | Current result |
| --- | --- |
| BOM → charset → strict UTF-8 → bounded detection/user choice | Priority/provenance and explicit-override fixtures pass. Authoritative strict UTF-8 no longer competes with legacy guesses. |
| No unrecorded `errors=ignore` in user content | Previously fixed filename sites remain covered. Replacement decoding in downloader diagnostics does not feed subtitle/note bodies. |
| Encoding/replacement/normalization/confidence | Decoder tests verify fields/raw digests. Transcript diagnostics now count U+FFFD/recognition markers and distinguish byte/Unicode corruption from sparse ASR uncertainty. Neither is called repaired encoding. |
| Corruption stops formal notes | Video/saved transcript gates preserve raw transcript plus `draft.review.md`, set `transcript_review_required` and `summary_generated=false`, and do not invoke the summarizer/create `note.md`. Usable text remains with `【识别不清】`. Model/page output uses the shared blocking gate/quarantine; code literals are not treated as prose corruption. |
| CJK/English/emoji, UTF-16/GB18030/CRLF/filenames | Five authoritative encodings yield one NFC note; existing CRLF/subtitle tests pass. Obsidian covers exactly 89 ASCII + compass, NFC, empty/path titles, identity, complete codepoints and UTF-8 budgets; legacy decomposed folders preserve annotations. |
| Markdown/ZIP/Obsidian/Notion/PDF/DOCX consistency | Mixed Chinese/Japanese/English/decomposed-accent/emoji/formula content passes actual Markdown/both ZIP handlers, Notion local payload, HTML/DOCX/PDF and actual Obsidian import. **PDF still substitutes Unicode names for emoji**; readability is not original glyph/text fidelity. |
| Raw input retained/redecode possible | Raw bytes/digests/re-decode API tests pass; new gates prove untouched transcript bytes. Current browser encoding-reselect flow was not repeated. |

Notion payload v2 removes silent truncation: 2,000 UTF-16-unit pieces, up to eight pieces/block, 100 blocks/request and conservative 450 KB request budget. A **1,205-block** fixture retains order across **13 batches**. Boundary emoji/large titles are tested; unrepresentable titles fail explicitly. Redaction precedes chunking. This validates local draft payloads, not a live Notion send.

**Keep #150 open:** literal PDF emoji fidelity still needs work; current browser re-decode and every source's provenance integration are not claimed by this package. The deterministic matrix and formal-publication gate are verified without calling recognition markers repaired text.

## #152 Semantic note structure

| Original criterion | Evidence |
| --- | --- |
| Single title/source/objectives | Exact duplicate-block tests, preserving different sources/nested metadata/personal notes. Semantic paraphrase deduplication is not claimed. |
| Front matter/separators as metadata | Shared canonicalization/export fixtures; code content preserved. |
| Continuous headings/stable anchors | Existing heading/stable-ID tests; HTML/PDF/DOCX share section identity. |
| Semantic long-paragraph splitting | Sentence-boundary tests; indivisible sentences and formula-containing paragraphs preserved, not arbitrarily cut. |
| Correct code/math/tables/images/quotes/CJK punctuation | Nested ordered/bullet lists, wrapped items, nested fences/indented code, escaped/code-span table pipes, quotes and grouped math in `test_nested_note_exports`; code indentation/trailing spaces and formula source retained. Existing image/alt/caption fixtures pass. |
| Prompt/internal-diagnostic leak detection | Prose-only gate fixtures; opt-in diagnostics limited to safe bounded machine statuses/issue codes. |
| #150 gate integration | Corrupt generated prose quarantined; unresolved transcript does not become a formal note. |
| Same model/local structure | Video/saved/subtitle-only/page-text model/local paths share normalizer, quality report, claim markers and note-document schema; `test_page_text_note_contract` verifies parity. Page text retains `can_claim_video_content=false`. |
| Bilingual/code/PPT/operation/empty snapshots | Existing six-shape corpus and new nested/page-text fixtures pass within 747-test run. No new live-model claim. |

Common grouped TeX becomes readable linear math: fractions, roots, sub/superscripts, Greek/operators. Original expressions stay in semantic blocks. Unknown commands remain literal with a warning. This is the bounded-parser approach allowed by the issue, not a native equation engine. **Recommend #152 for original-scope closure after CI/review.** Broader real-course evaluation remains follow-up, not an unlimited parser requirement.

## #156 Editable Word and print-ready PDF

| Original criterion | Current result |
| --- | --- |
| Chinese/English/emoji/math/code without garbling | Actual rendering exposed invisible Greek in PDF Type1 Symbol and missing Japanese glyphs inside DOCX code. Fixed using a local embedded symbol font and explicit split CJK runs. Actual screenshots show α, ∂, ≤ and 日本語. PDF emoji-name fallback remains a fidelity gap. |
| Editable headings/lists/tables | OOXML native headings, depth-specific numbering/start/restart/outer sequence, editable code/table text. No screenshot body substitution. |
| Embedded/reliable CJK font | Local embedding preferred; this host uses explicit STSong-Light CID fallback, rendered with Poppler. Host warnings surface. |
| TOC/header/footer/pages/pagination/widows | PDF linked multipass TOC with actual pages. DOCX native TOC/bookmarks/cached linked headings/updateFields and explicit host-refresh warning. Header title, A4, footer pages and widow control. Native Word refresh unperformed. |
| Clickable timestamps/claims/source | Source/time/TOC and keyframe links pass. **Claim-map-to-DOCX/PDF citation projection is absent**; ordinary timestamps do not prove stable claim citations are clickable. |
| Keyframe time/alt/caption | Four synthetic local frames/fixture; alt, caption/time links checked. No untrusted image fetch. |
| Inclusion options | Note/transcript/images/annotations/practice/sources/diagnostics choices; diagnostics default off. Built-in print/academic/compact are immutable/separate from custom names. Save selects custom preset; duplicate export/stale preview/source change/dismiss/reopen tested. |
| 30+ pages without overflow/blank anomalies | Exact matrix below. All-page text bounds and representative actual render review; not exhaustive overlap/widow visual proof. |
| Local conversion | App/LibreOffice/Poppler/import harness run locally; no third-party conversion. |

### Actual long-document matrix

| Output | Exact pages | Synthetic frame pages | Structural assertions |
| --- | ---: | --- | --- |
| print PDF | **36** | 9, 18, 27, 36 | 9/9 |
| academic PDF | **44** | 13, 23, 34, 44 | 11/11, including TOC |
| compact PDF | **41** | 11, 21, 31, 41 | 9/9 |
| academic DOCX → local LibreOffice PDF | **83** | Image/alt checked in OOXML | 40 editable tables and native TOC |

Print/academic use four paragraphs per each of 40 chapters; compact uses ten to exercise 30+ pages. This is not a same-input size comparison. All four outputs have zero out-of-media-box characters and no entirely empty text pages. Final academic PDF page has a short normal source/footer remainder. Small sample page 1 and academic PDF pages 1, 13, 44 were inspected. No every-page visual sign-off is claimed.

Committed nonprivate evidence:

- [PDF nested sample, actual page 1](qa/evidence-exports-20261008/nested-pdf.png)
- [DOCX nested sample, actual LibreOffice page 1](qa/evidence-exports-20261008/nested-docx-libreoffice.png)
- [Academic PDF, actual page 13](qa/evidence-exports-20261008/academic-pdf-page-13.png)
- [Revision/tests/pages/warnings/hashes/benchmark JSON](qa/evidence-exports-20261008/verification.json)

Complete synthetic files/renders/logs remain in ignored `build/evidence-followthrough`; their SHA-256 hashes are recorded. **Keep #156 open** for claim citations and PDF emoji fidelity, with host-field behavior explicitly documented. Unavailable WPS and unrestricted LaTeX are not extra closure requirements.
