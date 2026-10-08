# Evidence, Unicode, note structure and document export verification

Date: 2026-10-08. Issues: [#129](https://github.com/hurry060215-tech/learnnote-assistant/issues/129), [#150](https://github.com/hurry060215-tech/learnnote-assistant/issues/150), [#152](https://github.com/hurry060215-tech/learnnote-assistant/issues/152), [#156](https://github.com/hurry060215-tech/learnnote-assistant/issues/156).

## Result and revision

This package fixes reproducible defects and adds current regression evidence. **None of these four epics is eligible for full closure from this package.** Implementation gaps and unperformed acceptance checks are distinguished below. Earlier reports are background, not evidence for this revision.

- Starting revision: `768c46c47db44492f6c7283b7ed7f18f43de6073`.
- Unicode/filename fix: `69e4f4e`; claim publication fix: `a2b9cdf`; structure/export fix: `8817397`.
- Integration revision: `6cb4758`, incorporating main `dc257c83fc939582ca86c7cf3f7bc9b06cffb72c` without conflicts.
- Long-document artifacts were generated from clean `8817397d8d3fd4667585e5d73299ab3b0d454344`. The integrated revision does not change the note/export implementation.
- Environment: Linux cloud executor, Python 3.12.14, reportlab 5.0.1, python-docx 1.2.0, pypdf 6.19.0, Pillow 12.3.0, charset-normalizer 3.5.2. DOCX visual review used LibreOfficeDev 26.8.0.0.alpha0, not Microsoft Word or WPS.
- No new dependency, permission, model call, telemetry, third-party document conversion, or account change. Test-generated material is synthetic and local. No user annotations or original source bytes were overwritten.

## Current validation

On integrated `6cb4758`:

- `PYTHONPATH=backend:. python scripts/test-backend-offline.py`: **684 tests, pass, one existing platform skip**, 60.053 seconds. External DNS, HTTP and model-download attempts are denied locally by the runner.
- `PYTHONPATH=backend:. python -m unittest discover -s scripts/tests -p 'test_*.py'`: **100 tests, pass, two platform skips**.
- `python -m compileall -q backend/app`, `python scripts/check-architecture.py`, `node web/tests/markdown_render.test.mjs`, and `git diff --check`: pass.
- Before main integration, the same package passed 673 backend tests; these counts are separate runs, not additive.
- An initial invocation of an external runner with only `PYTHONPATH=backend` produced 13 import errors for the desktop package. Re-running with the repository root on the import path passed. The checked-in runner now configures parent and child import paths itself.

Reproducible focused checks:

```sh
PYTHONPATH=backend:. python -m unittest discover -s backend/tests -p 'test_claim*.py'
PYTHONPATH=backend:. python -m unittest discover -s backend/tests -p 'test_note*.py'
PYTHONPATH=backend:. python -m unittest discover -s backend/tests -p 'test_subtitles_first.py'
PYTHONPATH=backend:. python -m unittest discover -s backend/tests -p 'test_encoding_provenance.py'
PYTHONPATH=backend:. python -m unittest discover -s backend/tests -p 'test_document_exports.py'
PYTHONPATH=backend:. python scripts/claim-evidence-benchmark.py --output build/claim-report.json
PYTHONPATH=backend:. python scripts/export-long-document-qa.py \
  --output-dir build/export-qa --template academic --include-keyframes
```

The document export suite now has 21 tests. Generated PDFs, DOCX files, render images and run logs stay in ignored build directories; they are not committed as new source assets.

## #129 Claim-level evidence

| Acceptance condition | Current evidence and remaining boundary |
| --- | --- |
| Chinese entities, numbers, causes, steps and visual descriptions enter the gate | Existing bilingual/semantic fixtures and the 60-case public-source corpus pass their conservative review contract. Added short Chinese numeric claims, exact source spans and source/code/YAML exclusion tests. This is still a restricted prose projection, not exhaustive semantic extraction from tables, quotations, formulas or all Markdown. |
| Every factual claim has timed or visual evidence | Direct matches retain transcript/visual IDs and locators; document claims retain document locators. Unmatched claims remain review-required with no invented evidence IDs. An arbitrary paraphrase is not promoted merely because it has a timestamp. Full semantic support for every factual statement is not proved. |
| Click a claim to open subtitle/keyframe | Existing API/source-range contracts remain intact and the full backend suite passes. Claim map v6 adds exact Unicode-codepoint spans. A real browser click-through against a production task was not run here. |
| Unsupported claims cannot silently enter a formal note | Fixed production video and saved/subtitle-only persistence: pending, located-only and inference prose receives an explicit visible review marker before note.md is written. The final map is rebuilt against the published text. Verbatim evidence, source metadata, source-only notes and empty claim sets do not acquire invented unsupported claims. The page-text fallback path still needs the same publication contract. |
| Markdown, Obsidian and bundle references stay stable | Claim IDs now derive from task/text/duplicate occurrence rather than absolute list index, and survive unrelated preceding insertions. Review markers are portable Markdown. v4/v5 maps retain conservative verification but request a rebuild; no old offsets are fabricated. Current Obsidian client round-trip and all claim-specific document anchor navigation were not proved by this package. |
| Legitimate paraphrases are not removed by exact-string matching | Paraphrases are retained and visibly require review, rather than deleted or asserted false. Accurate automatic paraphrase support remains an implementation gap. |

The fixed public corpus contains 60 cases (30 English, 30 Chinese) from 12 recorded public sources. Current direct-support precision is **1.00**, recall **0.50**; review precision is **0.75**, recall **1.00**; false direct support is **0**. These are fixed-corpus status metrics, not general truth-verification accuracy. Twelve supported paraphrases still receive located-only/inference status. Do not describe this result as complete semantic verification.

## #150 Unicode and provenance

| Acceptance condition | Current evidence and remaining boundary |
| --- | --- |
| BOM, declared charset, strict UTF-8, bounded detection/user choice | BOM/declaration tests pass. Fixed valid strict UTF-8 being ranked against legacy guesses; it now wins before detection. An explicit user encoding remains an intentional override. |
| No unrecorded errors=ignore in user text paths | Removed the two filename truncation sites in library.py and main.py, replacing them with an NFC, complete-codepoint UTF-8 byte-budget helper. Remaining errors=replace in downloader_policy.py is bounded subprocess diagnostic decoding, not subtitle/note body ingestion. |
| Encoding, replacements, normalization version and confidence | Existing import metadata/raw digest tests pass, including explicit choice and HTTP/HTML declarations. UTF-8 replacement characters can no longer escape quarantine through another decoder. End-to-end manifests for every OCR/ASR/model-output source are still not fully unified. |
| Corrupt prose blocks publication | Canonical decoder and note-quality gates pass existing corruption fixtures. Code examples containing corruption strings remain literal code rather than being rejected as factual prose. |
| Chinese, Japanese, English, emoji, UTF-16, GB18030 and CRLF | Existing subtitle fixtures plus new mixed Han/kana/Hangul/Arabic/Latin/emoji authoritative-encoding tests pass. Filename tests exercise every byte budget from 0 through 219 without split codepoints or decomposed NFC output. |
| Markdown, ZIP, Obsidian, Notion, PDF/Word consistency | Current backend regressions pass. HTML now retains full Unicode and native inline code rather than inheriting PDF emoji substitutions. PDF CJK inline code avoids Courier, and Latin-1 symbols use a compatible font. A complete source-by-output import/export matrix, including a current Notion/Obsidian client round-trip, is still missing. PDF emoji remains an explicitly reported readable name fallback. |
| Original input retained and can be redecoded | Existing raw-subtitle and import/redecode API tests pass. The original-byte storage contract is unchanged. Current real UI reselect/redecode was not exercised in a browser. |

## #152 Semantic note normalization

| Acceptance condition | Current evidence and remaining boundary |
| --- | --- |
| Single title/source/learning objectives | Title tests remain green. Added exact repeated source/objective block removal, with changed sources, nested metadata and personal-note sections preserved. This does not remove semantically similar but differently worded duplicates. |
| Front matter and separators are metadata | Existing canonicalization and export tests pass. Fenced/indented code bytes remain preserved. |
| Continuous headings and stable anchors | Existing heading and anchor fixtures pass; PDF/Word heading projections now share the stable section identity used by HTML. |
| Semantic long-paragraph splitting | Existing sentence-boundary fixtures pass. Oversized indivisible sentences remain warned, not cut by arbitrary character count. |
| Code, math, tables, images, quotations and punctuation | Fixed code-span pipes inside table cells, escaped pipes, hard line breaks and blockquote adapters. Added editable ordered-list start/restart numbering and local-frame alt/caption coverage. Unicode formula characters render in the reviewed sample; arbitrary nested Markdown and native LaTeX/OMML remain implementation gaps. |
| Prompt/diagnostic leakage and mojibake | Existing prose-only blocking fixtures pass; code examples are not mistaken for instructions or course facts. Broad real-course/real-model false-positive evaluation is not included. |
| Same model/offline semantic structure | Both model/offline fixtures use note_pipeline, and saved/subtitle-only notes use the same normalizer and claim-publication marker contract. Page-text fallback still requires the unified structure/gate. |
| Multishape snapshots | Current six-case bilingual corpus and added focused regression shapes pass, including code, slide-like content, operation guides and absent evidence. These remain constructed fixtures, not a replacement for real lesson outputs. |

## #156 Word and PDF

| Acceptance condition | Current evidence and remaining boundary |
| --- | --- |
| Chinese/English/emoji/formulas/code without garbling | Fixed CJK inline code and the superscript-two/Latin-1 CID-font defect caught during visual inspection. PDF non-BMP emoji has an explicit name fallback warning; DOCX/HTML retain Unicode. Arbitrary LaTeX equations and universal emoji font fidelity remain unimplemented/unverified. |
| Editable Word headings/lists/tables | OOXML tests verify headings, native decimal-list sequences (including non-1 starts/restarts), and editable tables. No screenshot is substituted for Word content. |
| Reliable CJK font | Local font selection/CID fallback remains explicit. This Linux host uses STSong-Light plus Helvetica for affected Latin-1 glyphs, and rendered CJK was inspected with Poppler. Cross-viewer font reliability and embedded CJK coverage on every supported host are not proved. |
| TOC/page numbers/pagination/orphans | PDF now uses a multipass linked TOC with actual destinations/page numbers, and long TOCs start on the first page. Word gets a real TOC field, linked cached headings, stable bookmarks, updateFields and explicit refresh warning; page numbers require the host's field update. A4 and widow control are explicit. Native Word/WPS field refresh is still pending. |
| Clickable times/claims/source | Source/timestamp links and PDF TOC destinations are structurally tested. Embedded frame captions now link their timestamp to the sanitized source. A complete claim-anchor navigation matrix is still pending. |
| Keyframe time/alt/caption | Four local synthetic frames are embedded in the long fixture. DOCX alt descriptions and readable time captions are checked. Images honor the available landscape/portrait frame dimensions. No arbitrary external/local Markdown image is fetched. |
| Content inclusion choices | Existing note/transcript/image/annotation/practice/source options continue to pass. Backend print/academic/compact templates were added; no new UI template picker or diagnostic inclusion selector was added. Diagnostics and raw media remain excluded. |
| 30+ pages without clipping/blank anomalies | Clean code generated a 44-page PDF and a DOCX rendered by LibreOffice to 65 A4 pages. All-page character bounds found zero out-of-page characters and no empty pages; representative TOC, code/table, frame and final pages were visually reviewed. This is not a 100%-zoom visual sign-off on every page, and is not Word/WPS acceptance. |
| All conversion local | Confirmed by the local renderer calls and network-denied test suite. |

The long fixture checks 40 editable tables, first/last chapter presence, code, source links, emoji preservation/explicit fallback, four keyframes with alt metadata, at least 40 PDF internal TOC destinations and the native Word TOC field. All 11 structural assertions pass. The PDF and Word page counts are deliberately reported separately; no equality is implied across layout engines.

## Next closure work

1. Bring page-text fallback into the same semantic/claim publication path; extend span extraction to remaining factual Markdown structures and evaluate real paraphrases before calling #129 complete.
2. Build the full source/encoding/output matrix, including raw OCR/ASR/model provenance and current client re-decode/export checks for #150.
3. Complete nested Markdown and native equation adapters and genuine note-output fixtures for #152/#156.
4. Verify the live claim-to-subtitle/keyframe UI and Word/WPS TOC refresh, then inspect every page of the final long golden matrix. Browser UI and native Word/WPS acceptance are unperformed checks, not evidence that the existing code failed them.
