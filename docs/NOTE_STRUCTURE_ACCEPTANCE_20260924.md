# Note structure closeout evidence

- Date: 2026-09-24
- Baseline: `origin/main` `e585b7fbf3067d19f19d68760ff4614ad2757efa`
- Validated code commit: `f0f2a263615d89d06ff30f836ef377903ae3e1e2`
- Issue: [#152](https://github.com/hurry060215-tech/learnnote-assistant/issues/152)
- Scope: fix structural regressions found in the existing normalizer, shared export structure, and linter. This is a bounded acceptance increment; it does not claim arbitrary Markdown AST completeness.

## Changes

- Normalization now preserves trailing whitespace and Unicode inside fenced and indented code. Prompt-leak and mojibake checks inspect prose only, excluding machine-only YAML front matter and code examples.
- Reader/export projections omit YAML front matter. HTML export headings now use content-derived stable anchors that match the note-document section IDs; adding an unrelated section no longer renumbers existing anchors.
- Heading-level jumps are corrected without rewriting later section text. Plain long prose is grouped at sentence boundaries; paragraphs containing Markdown syntax or a single oversized sentence remain unchanged and receive a review warning when they exceed the threshold.
- Note document and quality report schema is version 2. Model and offline summary results still pass through the same persistence pipeline; blocking prompt-leak output is retained as a quarantine draft and not published as `note.md`.
- A six-case local fixture corpus covers English and Chinese, a code lesson, a slide-like note with duplicate headings, an operation guide, absent visible evidence, long Chinese prose, and prompt/garbling strings in code.

## Validation

Run with Python 3.12.10 on Windows:

```powershell
$env:PYTHONPATH='D:\learnnote-assistant-pkg3c\backend;D:\learnnote-assistant-pkg3c'
& 'D:\learnnote-assistant\.venv\Scripts\python.exe' -m unittest discover -s backend\tests -v
& 'D:\learnnote-assistant\.venv\Scripts\python.exe' -m unittest discover -s scripts\tests -v
& 'D:\learnnote-assistant\.venv\Scripts\python.exe' scripts\check-architecture.py
& 'D:\learnnote-assistant\.venv\Scripts\python.exe' scripts\audit-i18n.py
node web\tests\markdown_render.test.mjs
node --check web\desk.js
```

The focused note/export/pipeline tests exercise 6 fixture shapes, same-pipeline model/offline outputs, quarantine behavior, DOCX/PDF/HTML content, front matter removal, code whitespace retention, and stable anchors. The full backend suite passed 616 tests in 92.5 seconds; all 70 script tests passed. Architecture boundaries, i18n audit, the existing Markdown renderer suite, `node --check web/desk.js`, and `git diff --check` passed.

## Remaining boundaries

- Fixtures are constructed regression samples, not genuine course outputs. No real model call or media task was run in this package.
- `missing_visible_evidence` remains a warning in the linter; the video task's evidence-coverage gate is the blocking check. The fixture makes the warning visible but does not imply that every standalone document needs a video timestamp.
- Complex nested Markdown rendering and visual layout in Microsoft Word/WPS remain outside this focused regression; those exports still need long bilingual document inspection before #152 is closed.
- Unsupported prose that cannot be split safely at sentence boundaries is retained and warned, not edited by character count. Issue #152 remains open for the wider end-to-end acceptance.
