# Study/product issue acceptance audit — 2026-10-08

## Scope and evidence

Audited the original bodies and fetched comments of #136, #137, #138, #139,
#140, #141, #142, #144, #153, #157, #158 and #159. Historical roadmap notes
were context, not current acceptance evidence. No issue was closed here.

- Starting main: `768c46c`.
- Rebased main: `dc257c83fc939582ca86c7cf3f7bc9b06cffb72c` (#223).
- Product patch: `84dc7b3`; bilingual patch: `1d745e1`.
- Additional route-contract repair requested during review: `1af8b77`.
- Environment: Linux cloud checkout, Python 3.12.14, Node 24.19.0, existing test venv.
- Executed dependency versions: FastAPI 0.142.2, Pydantic 2.13.5, FSRS 6.3.2,
  pypdf 6.19.0. This was the shared installed environment, not a new Windows-lock
  installation; CI must still verify the repository-pinned installation.
- Inputs: synthetic text/PDF/media, local temporary databases, mocked site
  responses, DOM stubs. No paid model, real account, credentials, private
  video, desktop access, new permission or external comment capture was used.
- Supported cloud localhost browser access was blocked. It was not bypassed.
  Node DOM tests and CSS inspection do **not** establish screenshot, native
  extension, WebView, zoom, contrast, or low-end-device acceptance.

The existing approved #160 visual direction is retained. The small activity
calendar uses existing opaque-surface/color tokens; this is an acceptance/UX
addition, not a new visual concept or a wholesale stylesheet redesign.

## Delivered changes

1. Preserve explicitly selected legacy non-UTC plans during first-browser
   timezone initialization; return correct initialization state immediately;
   bound activity summaries to the selected local date range. Paused plans
   reject reading, answer, self-assessment and review writes without deleting
   cards. The UI offers resume and no longer reports paused work as completed.
2. Apply course filtering before quiz/mistake pagination and compute selected
   due totals correctly. Generated-note-only and community-only records cannot
   create evidence quizzes. Add stored-card editing and explicit permanent
   card/history deletion, a local review activity calendar and whole-study
   deletion controls. User-edited text and source anchors remain intact.
3. Route card, mistake and comparison evidence links using canonical task or
   material identity. Long transcripts follow playback outside the initially
   mounted rows, support keyboard movement to unmounted cues, and remove old
   source listeners when closed/switched.
4. Retain range-source page identity and nested original offsets, without
   carrying an original full-file fingerprint onto a new clip. Offer upgrade
   through verified stored full-video ancestry; reject missing/cyclic identity.
5. Keep default course batches text-first. Add course comparison source/type/
   time filters and prevent duplicate registration of the same evidence from
   creating a false two-source relationship.
6. Add a non-persisting document preflight with original filename, bytes,
   PDF pages, approximate local storage and extraction/OCR route before import.
   Fix `.markdown` detection. Reject stale preflights after changing file or
   encoding; selected-video metadata uses a temporary local object URL.
7. Filter obvious community promotion/player controls, redact recognizable
   contact strings, omit author labels, and deduplicate repeated text across
   timestamps. Grouping is clearly labeled as keyword hints. Add per-item
   deletion and an independent complete export beyond the UI's row limit.
8. Localize extension-owned static/dynamic/ARIA/error copy with 263 paired
   Chinese/English keys, bundled fallback, mutation-tested copy guards and two
   help documents. Preserve user-authored text and unknown provider diagnostics.
9. Remove duplicate export-preset GET registrations and unify historical
   name-map/list storage. POST IDs, named PUT, rename, deletion and OpenAPI
   method/path uniqueness have regression tests.

## Per-issue original criteria

“Proved” below means the stated deterministic invariant passed current tests.
“Implemented” means code is present but the requested end-to-end/visual matrix
has not been newly established. A missing feature is distinguished from an
external validation blocker.

### #136 — timezone-correct FSRS and pause

| Original criterion | Current evidence/result |
| --- | --- |
| First browser IANA suggestion, editable by user | Existing initialize/settings UI; one-time suggestion and manual persistence proved by `test_study_timezone_acceptance.py`. |
| Shanghai, New York, DST and UTC migration | Proved: exact Shanghai midnight, 23-hour spring-forward, 25-hour fall-back, UTC boundaries; legacy UTC initializes once while legacy non-UTC remains selected. |
| Reviewed-today and daily goal use plan timezone | Proved by boundary-inserted review fixtures and remaining-goal assertions. Future-day activity no longer enters summary totals. |
| Pause suppresses reminders/goal advancement, preserves cards | Proved: due/quiz queue empty, review and activity writes rejected, counts unchanged, resume retains cards. No background OS notification service is claimed. |
| UTC due-at storage | Proved after resumed FSRS review. |
| Import/export preserve timezone semantics | Proved backup restore into a fresh temporary database, followed by a different browser suggestion. |

**Closure recommendation:** eligible after integration CI passes. Actual OS
travel detection is not added as a new condition to this issue; the selected
IANA plan semantics, not geolocation, are the original requirement.

### #137 — current position, chapter and range

| Original criterion | Current evidence/result |
| --- | --- |
| Current position, chapter and custom range selection | Custom start/end and current-position-as-end exist in extension; workbench supports current-position-as-start. Chapter selector and explicit 5/15/30-minute presets are still missing. |
| Only selected-range evidence; visible bounds | Clip and subtitle-boundary tests prove no partial-cue text leak. Range tool now displays original bounds; full result/export boundary matrix remains incomplete. |
| Evidence returns to correct time | Relative clip cues, nested original offsets and source identity have tests; canonical citation navigation has Node tests. Real platform seek not rerun. |
| Page/part/tab mismatch blocks action | Existing extension identity/race tests pass, including Bilibili part/tab changes. |
| Reuse media and upgrade full video | Existing local clip reuse plus new verified ancestor upgrade path; missing/cyclic ancestry fails closed. Full UI processing path not browser-validated. |
| Bilibili, YouTube, local and generic HTML5 fixtures | Existing platform identity tests and real synthetic FFmpeg clip test pass; a combined all-platform range/chapter matrix is not present. |

**Keep open:** missing chapter/preset functionality and full range acceptance.

### #138 — course batch workspace

| Original criterion | Current evidence/result |
| --- | --- |
| Manual course, Bilibili multipart and public playlist fixtures | Manual grouping and bounded, no-download playlist preview exist; public playlist fixture tests pass. Dedicated Bilibili episode lifecycle matrix remains incomplete. |
| Independent checkpoint/retry/resource budget per episode | Each submitted source is a normal checkpointed task with shared scheduler limits. Course-level episode controls/status/resource-budget acceptance is incomplete. |
| Subtitle-first batches, optional later deep upgrade | Default workbench batch now explicitly uses text mode with visual understanding off. Existing per-task rerun retains optional upgrade. |
| Course conclusions cite episode and time | Local comparison returns source ID/title, locator and evidence IDs; no uncited generated comparison is introduced. Broader course Q&A acceptance remains incomplete. |
| Duplicate media avoids download/index duplication | URL dedup and stable handoff IDs exist; source-alias comparison duplication repaired. Cross-course media processing/download dedup still needs its own fixture matrix. |
| Pause/reorder/delete course, choose whether to delete children | Pause-before-next-submit, reorder and keep-source deletion have tests. “Delete course and children” is not implemented. |

**Keep open:** remaining course lifecycle and deletion-choice functionality.

### #139 — unified evidence timeline

| Original criterion | Current evidence/result |
| --- | --- |
| Player synchronizes subtitles, frames and notes | Subtitle follow repaired and tested; a continuously synchronized frame/note track is not implemented in the current reader. |
| Subtitle-only returns via extension/deep link | Existing source panel/original-page link paths remain; current real browser path not rerun. |
| Wrong active tab cannot seek | Existing extension identity tests pass. |
| Long transcript virtualization | Proved with 10,000-cue Node fixture: bounded mounted rows, far-ahead follow, no redundant replacement, keyboard Home/End, stale-listener cleanup. Variable-height/zoom visual behavior still needs browser review. |
| Claim/card/Q&A citation share anchor | Cards, mistakes and comparison now use canonical source resolver; claim and Q&A paths retain their existing source handling. One consolidated multi-track component is still incomplete. |
| Keyboard, ARIA, 200% and mobile | Native cue buttons have explicit ordinal/time/text labels and off-window keyboard tests; visual/zoom/mobile matrix not run. |

**Keep open:** multi-track implementation plus original visual acceptance.

### #140 — persistent personal annotations

| Original criterion | Current evidence/result |
| --- | --- |
| Personal and generated content stored separately | Existing `personal_notes.py` and tests prove separate local layer. |
| Survive regeneration, upgrade, restore and Obsidian sync | Regeneration/reimport and learning-backup restore fixtures pass. This task did not modify or validate Obsidian integration. |
| Anchor to claim, subtitle range and visual window | Current saved anchor supports revision/locator/selected text; first-class claim/window selection and migration are incomplete. |
| Visible orphan repair | Existing changed-revision detection and explicit re-selection repair UI/contracts pass. |
| Generated-only or personal-inclusive export | Existing include-annotations option and backup/export fixtures pass; broader export worker owns format fidelity. |
| No silent i18n/model rewrite of user content | Personal storage remains independent; extension user-text preservation tests pass. |

**Keep open:** explicit claim/visual-window anchors and original Obsidian criterion.

### #141 — evidence quizzes, mistakes and mastery

| Original criterion | Current evidence/result |
| --- | --- |
| Every question has an evidence/claim anchor | Canonical evidence required by creation API; answers stay hidden in dashboard queue. |
| No sufficient evidence means no question | Missing IDs, caption fragments, generated-note-only and community-only inputs rejected by focused tests. |
| Mistakes return to subtitles/keyframes | Canonical task/material navigation now used instead of only displaying a detached excerpt; timestamp resolution tested. Full keyframe navigation is incomplete. |
| Edit/delete wrong questions | New content PUT and explicit permanent DELETE, with UI in revealed-card view; anchors, exact user text and schedule/history preservation tested. Deleted card, reviews and card activity disappear from exports/dashboard. |
| Mastery distinguishes seen, correct, stability and self-assessment | Reading/answer/self-assessment actions and FSRS stability buckets remain separate. No objective answer-correctness model or independent correctness UI is claimed. |
| Records pause/export/delete | Paused activity/review writes rejected; full export/restore and complete study-clear controls exist and deletion rebuilding is tested. |

**Keep open:** original mastery correctness distinction and full multimedia
mistake navigation still need completion. Additional complex quiz types are
not invented as a closure condition.

### #142 — cross-source concepts/comparison

| Original criterion | Current evidence/result |
| --- | --- |
| Every edge has two source evidences | Proved for keyword co-occurrence, including rejection of the same evidence registered twice under task/material aliases. |
| Course/video/time/source-type filters | Course selects scope; new source ID/type/time filters and tests are present. |
| Split/merge same-name concepts | Not implemented. Current graph nodes represent sources and keyword matches, not an editable normalized concept model. |
| Distinguish inferred and factual edges | Current graph explicitly labels keyword co-occurrence and never claims synonymy/causation/agreement. General inference/fact-edge model is missing. |
| Rebuild corrupted index locally | Existing task-index rebuild tests pass. It is not a persisted concept graph or complete document-index reconstruction. |
| Answers cite source video/time | Local comparison exposes title, locator and evidence ID, now with clickable canonical source links. |

**Keep open:** concept model/split/merge/incremental reconstruction are genuine
remaining development, not merely missing screenshots.

### #144 — bilingual extension

| Original criterion | Current evidence/result |
| --- | --- |
| Manifest default locale | Present and audited. |
| UI/error/accessibility translation and fallback | 263 paired keys, bundled fallback and known product-error boundary; English/Chinese/fallback DOM tests pass. Unknown backend/provider diagnostics intentionally retain original wording. |
| Both store locales have screenshots/support | Both help documents/listing descriptions exist. Actual locale-specific screenshots are missing. |
| User content stays original | Explicit tests for titles, subtitles, notes and prompts pass. No document-wide translation observer. |
| 390/768/desktop panel layout | Preventive wrapping/min-width fix only; real viewport/overflow testing not run. |
| CI missing-key zero, new copy enters resources | Audit and 9 deliberate-mutation tests pass; dynamic/static/ARIA/placeholder/load-order/fallback and service-copy guards run in existing CI. |

**Keep open:** screenshots and original real-layout criteria.
See [localization report](EXTENSION_LOCALIZATION.md).

### #153 — approved shell/readability acceptance

| Original criterion | Current evidence/result |
| --- | --- |
| Clear primary task, no duplicate CTAs/internal terms | Existing new-note shell and contract tests retained; this task adds no competing primary navigation. |
| Long-form width/type/line-height/hierarchy | Existing opaque reader/tokens retained; no new typography concept. |
| Consistent claim/subtitle/frame/inference states | Existing labels retained; full multi-track consistency remains tied to #139. |
| Export/version/review/assistant are clear secondary actions | Existing reader/tools layout retained. |
| 390/768/1024/1440 and 90–200% | Current browser matrix not run. |
| Contrast/keyboard/forced-colors/reduced motion/transparency | Existing static/accessibility contracts pass; new cue keyboard tests and activity forced-color rule exist. Full runtime contrast matrix not established. |
| WebView/low-end blur performance | Not measured in this Linux cloud task. |
| Concept-to-browser fidelity review | Existing approved #160 references are accepted context; no new complete fidelity ledger produced. |

**Keep open:** requested visual/performance evidence. No new concept approval
is requested because no redesign was attempted.

### #157 — learning materials hub

| Original criterion | Current evidence/result |
| --- | --- |
| PDF/Markdown/HTML/TXT/video discoverable from first screen | Existing unified file picker retained; `.markdown`/`.htm` support aligned with backend. |
| Before import: file/pages-duration/space/route | New non-persisting document preflight proves PDF page count, text preview, storage estimate and local/OCR route; selected video reads browser metadata when supported and states upload-space lower bound. Full decoded-video size estimate remains unavailable. |
| PDF pages, document paragraphs, video times | Existing anchor tests pass; range and canonical video identity tests added. |
| Optional local scanned-PDF OCR with confidence | Existing optional OCR engine/line-confidence contract and scanned-PDF fixture pass. Preflight exposes OCR-required route; real OCR/browser confidence display not newly validated. |
| Hash dedup and rebuild from original file | Import dedup and raw-byte preservation tests pass. The subsequent document rebuild work restores TXT/Markdown/HTML/PDF evidence IDs, locators, original bytes and card backlinks (`test_material_rebuild.py`); whole-database disaster recovery is not this criterion. |
| Courses and scoped Q&A | Course comparison alone did not satisfy this criterion. A dedicated selectable course question form now calls `/api/courses/{id}/ask`; canonical member IDs restrict FTS/LIKE and optional local reranking before result limits. Empty/deleted/stale scopes never use global evidence. It returns cited local extracts, not model synthesis. See [focused acceptance](COURSE_QUESTION_ACCEPTANCE_20261009.md). |
| Index deletion preserves user original | Existing local-video registration reuses source and keep-source deletion tests pass. |
| Path/name/content encoding | Existing filename/encoding tests pass, plus `.markdown` route/preflight. Broader #150 work is owned by evidence/encoding patch. |

**Verification boundary:** the course increment has offline API and UI behavior
tests plus a synthetic Windows Edge fixture in the UI gate. Its exact-head Edge
result and the existing video/OCR fixtures must be checked on the integrated
branch before claiming browser acceptance. Full-media backup and whole-database
disaster recovery are not invented as new standalone closure conditions.

### #158 — optional community perspective lane

| Original criterion | Current evidence/result |
| --- | --- |
| Off by default, no transcript contamination | Existing opt-in/local-only tests pass; no site fetch is added. |
| Course claims cannot rely only on comments | Community storage remains outside primary evidence; quiz gate additionally rejects community records. |
| Audience viewpoints/questions/disputes, not facts | New keyword groups and explicit non-factual UI labels. This is not semantic consensus analysis. |
| Remove ads/repetition/controls/obvious PII | New deterministic best-effort filter and tests; repeated timestamps no longer bypass dedup. It does not claim perfect PII recognition. |
| Omit/minimize authors | New stored samples omit author identity; list/export do not expose legacy author labels. |
| Delete/exclude/separate export | Per-item deletion, whole-task deletion, disable and independent JSON export; 2,001-row export fixture proves no UI-page truncation. |
| Capture failure does not block main task | Lane remains separate; Bilibili-specific user-triggered capture adapter is still absent, so its failure matrix cannot be claimed. |
| Privacy/site boundary documentation | PRIVACY.md explicitly describes local input, best-effort filtering, grouping and lack of authenticated crawling. |

**Keep open:** original first-platform capture adapter and its failure/permission
acceptance. Manual paste is not presented as Bilibili capture completion.

### #159 — daily learning studio

| Original criterion | Current evidence/result |
| --- | --- |
| Due/goal/one primary action on first screen | Existing overview retained; resume replaces start when paused. Selected-course due count fixed. |
| Cards/quizzes/mistakes return to claim/subtitle/frame | Canonical evidence navigation added for cards/mistakes; complete frame/claim path remains incomplete. |
| Distinguish generated/learning/stability/self-assessment | Counts, FSRS buckets and local action categories are separate; answer-correctness limitation is recorded under #141. |
| Course/video filtering | Course queue/mistake filtering is now before pagination. Standalone video filter in studio is still missing. |
| Pause/timezone follows #136 | Proved by deterministic migration/DST/pause tests. |
| Quiz evidence gate follows #141 | Current negative/canonical-evidence tests pass. |
| Local records only for activity heatmap/streak | New 14-day activity grid uses backend local review counts and selected plan timezone, with date/count accessible labels. No platform progress or telemetry. No all-time streak claim. |
| Delete data rebuilds/clears statistics | Whole-study clear UI added; card and whole-study deletion/export/dashboard tests pass. |
| 390/768/1440 and keyboard | Node contracts and native controls only; current browser viewport matrix not run. |
| Approved glass shell, opaque content | Existing direction unchanged; calendar uses existing opaque tokens. |

**Keep open:** original video filtering, multimedia/mastery dependencies and
current visual acceptance.

## Verification commands and results

Run from repository root with the existing test virtual environment:

```sh
python scripts/test-backend-offline.py
PYTHONPATH=.:backend python -m unittest discover scripts/tests -p 'test_*.py'
PYTHONPATH=.:backend python -m unittest desktop.tests.test_desktop_launcher
python -m compileall -q backend/app
for f in web/tests/*.test.mjs extension/tests/*.test.mjs; do node "$f"; done
python scripts/audit-i18n.py
git diff --check
```

The offline runner rejects external DNS/socket/HTTP/yt-dlp requests. The final
post-review aggregate results are recorded below when complete; earlier green
runs are not substituted for the final patch. Browser/real-model/platform tests
listed above remain explicitly unrun.

Final code result at `1af8b77` (documentation-only commit follows):

- Backend offline aggregate: **682 tests, passed**, 1 optional-platform skip.
- Script aggregate: **109 tests, passed**, 2 optional-platform skips.
- Desktop launcher: **28 tests, passed**.
- Web: **26 Node test files, passed** on rebased code.
- Extension: **60 Node test files, passed**; no extension edits followed that run.
- Localization audit: **263/263 paired keys; zero missing keys, locale/parameter
  mismatches, hardcoded panel findings or unlocalized known service errors**.
- Compileall and `git diff --check`: passed.
- Browser screenshots, physical OS/DST travel, WebView/low-end rendering,
  real-model quality, authenticated platform capture and Obsidian integration:
  not run in this task and not counted as passing.

The initial external offline-runner invocation needed `PYTHONPATH=.:backend`
(the repository root is needed by desktop-import tests). The now-versioned
`scripts/test-backend-offline.py` from #223 handles root/import paths itself;
the final aggregate used that versioned runner.
