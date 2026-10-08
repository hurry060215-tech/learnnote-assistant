# Independent course/range/locale acceptance — 2026-10-08

Initial base: `fdadce2e6f96d27f2e4fca4c60d116b9be150788`; final integration adds
main `e64f15d5753248bcb2b85338f881c457592df8f2` and its JavaScript graph guard.
This patch isolates the unaffected original study/product requirements. The
community production module and its existing privacy test are byte-identical
to this main revision. No new community capture endpoint, extension sampler,
opt-in UI, email scanner or redaction regression is included. The separate
security PR #236 remains paused; this patch is not a substitute for its update.

## Scope

- Issue #138: durable episode-to-task journal, source-bound stable handoffs,
  lost-ack reconciliation, concurrent/stale-prepare safety, same-task resume,
  fresh reorder projection, pause-before-next-submit and text-first batches.
  Linked URL episodes contribute their canonical course evidence.
- Issue #137: discoverable current-position 5/15/30-minute, source-chapter and
  custom ranges. Native chapter tracks and bounded source-matched DOM/JSON-LD
  evidence only; inaccessible tracks fail gracefully. Recheck source/time on
  submission. Forward `learning_range` through the background handler and
  reject a reused handoff with a different range or Bilibili part.
- Issue #159: course/video scope intersection before pagination, visible video
  selector, preserved review/resume scope; global plan/activity totals remain
  explicitly all-source statistics.
- Issue #144: 273 paired locale keys after adding range copy; no new community
  copy. Actual shipped panel rendering in Windows Edge CI: both languages,
  390/768/1440 widths, 90/100/200% effective zoom, loading/connected/error/results,
  plus offline/incompatible states and four bilingual 1280×800 store candidates.
- Issues #153/#159: actual default reader/studio Windows CI matrix at
  390/768/1024/1440, 90/100/200% effective zoom and light/dark; geometry, contrast,
  opaque reader, keyboard reveal/edit/delete/pause/resume and accessibility
  preferences. The existing approved visual direction is unchanged.

The chapter helper has ordered explicit injection, distribution allowlists,
shared VM loading, i18n audit coverage and unchanged combined-byte budgets.
Main's capture helpers, synchronous `importScripts` loader, queue resource label,
local support UI and export-panel updates are preserved.

## Verification boundary

The browser runners render the real shipped UI. Chrome runtime/storage/tabs/
permissions/i18n and extension service replies are synthetic fixtures; the
study runner uses the real isolated backend with local synthetic materials and
canonical cards. Neither uses accounts, paid models or real website capture.
Effective CSS viewport/device-scale stress is documented, not claimed as native
browser toolbar zoom. Native extension installation/permission prompts and
WebView/low-end hardware performance are not established by these runners.

Both browser-free `--self-test` modes passed. Rendered results and screenshots
remain pending the independent draft PR's Windows CI. No cloud browser access
was attempted after the earlier policy block.

## Original-criterion disposition

- Issue #137: controls/identity/transport are implemented and deterministic
  fixtures pass. Broader rendered platform range/export acceptance remains.
- Issue #138: episode persistence/retry/order/pause criteria now have fixtures;
  cross-course media dedup and delete-children choice remain separate gaps.
- Issue #144 remains open: the 18-condition actual extension render passed and
  candidate screenshots exist, but images are unreviewed and not persistently
  archived. No image-access workaround or store upload is added.
- Issue #153: retain existing #160 approval and prior native evidence; the new
  matrix covers layout/contrast/keyboard. Exact low-end performance and itemized
  concept-to-final visual comparison remain unproven by this patch.
- Issue #159 remains open: data invariants, video/course scope and timed subtitle
  navigation are covered, but the resolver does not dispatch claim_id/window_id
  to a selected claim or keyframe. The current rendered matrix uses material
  evidence and cannot establish the missing claim/frame paths. A separate quiz
  database schema is not added as an extra requirement.

No issue is automatically closed by this patch. Final CI counts and artifact
links are recorded in the draft PR rather than represented as already passed.

## Rendered checkpoint (before final integration)

At head `fd8491747ff555c1ac8c7e92dcaad0c09762d0e8`, the actual extension runner
passed all 18 conditions and generated four bilingual store candidates. The
subsequent default-reader stage exposed a 390/200% overflow, so the complete UI
workflow was not green. Screenshots were uploaded in
[run 37802466976](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37802466976)
(artifact 11560713522), but the images have not been manually inspected.

Followup fixes preserve newer keyboard focus when the source-dialog close event
arrives late, and make the actual keyboard review check wait for the completed
close, confirm focus and the review POST, inspect the unique persisted rating,
and compare progress with the server. A controlled DOM regression reproduced
the old focus theft before the fix. The narrow reader/toolbar repair keeps the
runtime CSS at 2249/2250 lines by removing only an earlier success-state padding
block fully overridden by the existing later rule. No matrix or budget is relaxed.
