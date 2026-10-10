# Export and study acceptance closeout, 2026-10-10

Tested product revision: `09dbaf632ed33abd4a4795429167123d784e8579`.
This record changes documentation only. All new inputs were synthetic and local;
no real learning data, provider credentials or paid model calls were used.

## Export issue #156

The original bounded criteria were rechecked after
[#250](https://github.com/hurry060215-tech/learnnote-assistant/pull/250),
[#290](https://github.com/hurry060215-tech/learnnote-assistant/pull/290) and
[#292](https://github.com/hurry060215-tech/learnnote-assistant/pull/292).
The [completion evidence](https://github.com/hurry060215-tech/learnnote-assistant/issues/156#issuecomment-6098373755)
was posted before the issue was closed as completed at 14:13 UTC.

| Original criterion | Evidence and limit |
| --- | --- |
| Chinese, English, emoji, formulas and code | Current actual-format regressions and rendered long-document samples preserve text and monochrome emoji. Formulas use the documented bounded readable projection, not an unrestricted equation engine. |
| Editable Word headings/lists/tables | Native OOXML structures, numbered/nested lists, forty editable tables and code text are checked. The body is not a screenshot. |
| Embedded or reliable CJK PDF fonts | Existing font embedding/CID fallback is retained. This host reports its STSong-Light fallback; Poppler renders the Chinese text. |
| TOC, headers, footers, pages and pagination | The academic PDF has linked page-numbered TOC entries; rendered header/footer pages and existing widow-control contracts pass. DOCX has native fields and a visible field-refresh warning. |
| Clickable time, claim and source links | Actual DOCX relationships, PDF annotations and HTML anchors pass, including complete escaped destinations and stable claim references. |
| Keyframes with time and descriptions | Four task-owned synthetic images retain alt/caption and clickable time metadata; unrelated remote images are not fetched. |
| Inclusion choices | Existing note, transcript, frame, personal-annotation and diagnostic options pass; diagnostic content remains opt-in. |
| Documents longer than thirty pages | Three current templates and all-page geometry results appear below. |
| Local conversion | The application, fonts, document inspection and rendering run locally. Source Markdown is unchanged. |

Current `scripts/export-long-document-qa.py --include-keyframes` results:

| Template | PDF pages | Empty text pages | Words outside page bounds |
| --- | ---: | ---: | ---: |
| print | 36 | 0 | 0 |
| academic | 44 | 0 | 0 |
| compact | 41 | 0 | 0 |

All structural checks passed, including literal emoji in extracted PDF text,
editable DOCX tables, code, source relationships, frame alt text and the academic
TOC. Poppler rendered academic pages 1, 13 and 44, print page 36 and compact page
41; these five images were inspected. All 121 PDF pages were checked for text
bounds and empty text pages. This is representative pixel review plus complete
geometry checks, not a claim that every page was manually reviewed.

Earlier [local LibreOffice DOCX rendering](../ISSUE_EVIDENCE_EXPORT_20261008.md#actual-long-document-matrix)
remains historical evidence for its recorded revision. No native Word/WPS session
or fresh LibreOffice render ran in this pass. DOCX TOC page numbers require the
viewer to refresh fields. Those host boundaries remain explicit; unavailable WPS
and unrestricted LaTeX are not additional original issue requirements.

## Study issue #159

An independent audit found no unmet original criterion. The
[current completion evidence](https://github.com/hurry060215-tech/learnnote-assistant/issues/159#issuecomment-6098377393)
and [earlier actual Edge evidence](https://github.com/hurry060215-tech/learnnote-assistant/issues/159#issuecomment-6077718260)
support closing this issue as completed at 14:13 UTC.

The ten checked areas were: due count/goal/primary action; canonical card, quiz
and mistake navigation; separate generation, learning, objective results,
self-assessment and FSRS stability; course/video filters; pause/timezone;
evidence-gated questions; local review heatmap; statistics rebuilt after deletion;
responsive keyboard paths; and opaque, high-contrast reading surfaces.

Current focused checks passed **130 guarded backend tests and 39 Node entries**.
They include study, source, personal-anchor and community-isolation contracts,
not 130 exclusively studio tests. The shipped study fixture tests responsive
widths, keyboard reveal/edit/delete/pause/resume and reduced visual effects.
The [actual Edge run for the final product tree](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38057432186)
passed. Native WebView performance and unfinished dependency epics retain their
own acceptance boundaries; they are not silently claimed by this closure.

## Current integrated evidence

- Final product tree: `176249ac20aca03f8a311bde7db0d89088664130`.
- Full guarded backend: **1,181 passed**. Script/desktop: **203 run, 200 passed,
  three existing platform skips**.
- Independent link audit: **93 actual DOCX/PDF/HTML cases** and five timestamp
  protection probes passed. Twelve committed regression tests cover the parser
  increment. Source-bearing titles are preserved during title cleanup.
- All six PR workflow groups passed at `3d58108827d1a8651386c465e9c76718ad031d0d`;
  detailed CodeQL reported zero new alerts and no review threads remained.
- All six triggered main workflows passed, including the dependency graph update.
  [Main CI](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38057823613),
  [reliability](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38057823631)
  and [container](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38057823743)
  identify the exact product revision.
- Published image digest:
  `sha256:1b61b8de081f32ffc2faec24711162303d87f5b4bcf8c010239870fbfa75e1eb`.
  Both amd64 and arm64 installed the pinned Markdown dependencies and actually
  ran the PyAV 18.1.0 decoder check. No model was downloaded.

## Open scope and corrected stale entries

Complete pagination at 14:13 UTC found **19 open issues**, excluding PRs, with an
empty second page: #52, #55, #70, #129, #135, #137, #138, #139, #140, #142, #143,
#146, #147, #148, #149, #151, #153, #158 and #276. The two open PRs #249/#277 remain
paused. No other epic or roadmap item was closed.

- #158 currently offers manual paste. Its sampling endpoint samples stored
  excerpts; a Bilibili comment/danmaku capture adapter is **not implemented**.
  Official interface, authorization and platform terms must be checked before
  automatic collection. Neither browser access nor visible page content alone
  establishes that permission. The existing supplied-sample privacy statement
  remains accurate.
- #287 already adds visual batches at matching source-time sections while
  preserving source DOM, selection and scroll. #288 supplies measured historical
  reference intervals only after transcript readiness, using compatible local
  samples. It does not supply whole-task estimates or provider prices.
- #148/#151 still lack the broader semantic/per-section verification evidence.
  The earlier two-hour SSE attempt stopped at 115.6 minutes without its terminal
  comparison. It remains **interrupted**, was not rerun in this pass and cannot
  be described as a two-hour success.
- Real native permissions, external signing/store access, native Obsidian,
  low-end hardware, semantic quality and explicitly paused publications retain
  their recorded limits. No new permissions, accounts or collection were enabled.
