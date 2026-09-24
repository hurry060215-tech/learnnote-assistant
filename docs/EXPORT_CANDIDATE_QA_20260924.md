# Export and distribution candidate QA

- Date: 2026-09-24
- Baseline: `origin/main` `e585b7fbf3067d19f19d68760ff4614ad2757efa`
- Candidate code commit: `69d2691`
- Related issues: [#156](https://github.com/hurry060215-tech/learnnote-assistant/issues/156), [#134](https://github.com/hurry060215-tech/learnnote-assistant/issues/134), [#55](https://github.com/hurry060215-tech/learnnote-assistant/issues/55)
- Samples and extension package are under ignored `build/package6/`; no user content was used.

## DOCX/PDF sample

The app exporter processed a constructed 500-paragraph bilingual note with 50 tables, code blocks, Greek math symbols, a long URL, 500 time ranges, source links, and personal notes.

- The application PDF renders to 52 A4 pages. It contains 509 clickable PDF links, including source and timecode links; all 50 tables render without split-row or clipping defects. Chinese and Greek math text remains readable.
- The app PDF renderer cannot encode the test emoji as a glyph, so it emits a readable Unicode-name fallback (`[compass]`) and reports `non_bmp_symbols_rendered_as_unicode_names`, instead of outputting a blank square.
- The DOCX contains 50 editable OOXML tables, 504 hyperlink references / 54 distinct relationship targets, and PAGE/NUMPAGES footer fields. A read-only Microsoft Word export rendered to 89 Letter pages; the final PDF page field displays `LearnNote · page / 89`. Non-BMP emoji uses Segoe UI Emoji and rendered as a compass in Word.
- Word's pre-export COM `ComputeStatistics` returned 118 pages while Word's exported PDF and PAGE/NUMPAGES footer report 89. The exported file preserves the full 500-section body through section 10.50; native Word/WPS page-count parity still needs direct UI inspection. WPS is not installed.

Both application PDF and Word-rendered PDF were rasterized at 100 dpi and reviewed across all pages using page contact sheets, plus full-size title/body pages. No clipped text, overlap, broken tables, missing CJK glyphs, or blank-page anomaly was seen. Poppler emitted missing display-font warnings for Symbol/ArialUnicode, but rasterized formula pages showed the expected symbols. Rendered images and export artifacts remain under ignored `build/package6/exports-long-sample/` and `build/package6/render-*/`.

## Extension candidate

`package-extension.ps1` created `build/package6/LearnNote-Extension-Candidate.zip`; `validate-store-package.py` passed against manifest version `0.2.14`. SHA-256: `121f3002acd5862abdc4eba80844c16724831a48e06084c5f24beb304de2a6ae`; size: 139,317 bytes. This is a local candidate and was not uploaded or submitted to a store.

## Validation and boundaries

- Python 3.12.10 / Windows full backend suite: 608 passed in 92.1 seconds.
- `scripts/tests`: 70 passed.
- All `web/tests/*.test.mjs`, JS syntax, architecture, i18n, and `git diff --check`: passed.
- Focused export regression: 9 tests, including editable Word tables, Unicode fallback, timestamp/source hyperlinks, redaction, and PDF output.
- Windows installer install/upgrade rollback was not run: `ISCC.exe` and a disposable previous/current installer pair are not present. No installer build, Release, tag, signing, or update was attempted.

#156 remains open for direct Word/WPS UI pagination reconciliation, page-numbered/linked TOC, WPS rendering, further math/formula coverage, and 30+ page native editing. #134 remains open for real installer transaction/retry/rollback; #55 remains externally blocked on store listings, signing, and ordinary-user install/upgrade. No Release or store submission is included.
