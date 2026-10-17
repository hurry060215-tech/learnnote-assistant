# #158: explicit visible-community preview and selected save

## Scope and acceptance status

This slice adds the missing user-triggered Bilibili visible-page adapter to the
existing manual community-perspective lane. It does not require an official API,
use private APIs, or claim live-platform coverage from synthetic fixtures.

The original eight acceptance requirements map to: (1) default-off lane and no
transcript insertion, (2) no community-only course claims, (3) clearly labelled
unverified audience views, (4) control/promotion/contact filtering and dedup,
(5) omitted author identity, (6) explicit pre-save exclusions plus existing
Delete/Clear/separate Export, (7) capture failure isolated from the main task,
and (8) synchronized privacy/site boundaries. These are covered by the code and
contracts listed below; actual rendered UI acceptance is a separate hosted gate.

The broader original Scope also names temporal peaks, semantic clustering and a
Q&A inclusion switch. This adapter does not implement those features. Existing
keyword categories remain explicitly qualified organizational hints. A small
viewport snapshot is not a representative frequency or consensus sample. No
additional heuristics, model defaults, Q&A context or claim provenance are added.

## Boundary and data flow

1. A current-task sidepanel disclosure explains the local destination and limits.
   Opening it, page navigation, playback and task creation never collect text.
   Enable is a separate explicit local setting; the lane remains off by default.
2. Preview checks the existing site grant, exact tab, supported HTTPS host/path,
   video and numeric Bilibili part. It injects the pure collector into frame 0 only.
   It never requests a permission or falls back to another active tab.
3. The collector reads known comment-body/danmaku shapes, including supported
   open shadow roots. Full bounds must fit the viewport and ancestor clipping;
   center/corner hit tests reject detected overlays. It skips unsupported,
   partially visible, hidden, control, author, iframe and closed-root content.
   Hit tests are conservative samples, not a pixel-perfect visibility guarantee.
   Limits: 20 items, 2,000 characters/item, 20,000 total, 1,500 nodes, depth 60.
4. The bounded payload goes only to the displayed validated loopback origin.
   Existing export/summary sanitizers and community filters run before any
   preview caching. Review shows literal sanitized text and initially unchecked
   boxes. No raw samples enter extension storage, task files or diagnostics.
5. Only selected item IDs plus the immutable preview token/fingerprint can be
   saved. Five-minute, single-use tokens bind the source/task revision and local
   storage scope. Global disable/clear invalidates earlier generations. Cache is
   capped at 64 previews globally/16 per storage scope and pruned on later calls.
   Cancellation clears browser state; it does not promise immediate server RAM
   erasure or undo of a save already accepted by the local service.
6. Repeated async identity and permission checks reject stale captures. A tab,
   video/part, task/backend or permission change discards pending browser review.
   Save uncertainty remains visible even after a later close/toggle; no auto-retry.

Only canonical video path and validated `p` survive in stored source URLs.
Unknown timestamps remain null; player time is never invented as source time.
Current-page caption-only completion is supported through its full admission
identity. Local/imported/unbound subtitle tasks and page-text tasks fail closed.
No new permissions, dependencies, database migration or model request is added.

## Reuse and module/size decisions

`community.py` owns shared sanitization, dedup, quotas, storage and revocation.
`community_capture.py` owns only bounded transient review. A small dedicated
router gives non-reflecting validation errors; `knowledge_study.py` only includes
it. The separate `main.py` commit classifies exactly `/community-context/preview`
and `/community-context/save` under the existing 2 MiB write envelope; strict
20-item/20,000-character validation remains at the endpoint. No general limit
was increased. Existing delete/export/evidence filtering are reused unchanged.

The extension reuses pairing headers and sidepanel identity state. The broad
media/cookie capture pipeline was unsuitable: it collects broader page/media
context, has fallback behavior, and has unrelated persistence/retry semantics.
A tiny pure identity/origin helper is shared across transport and UI; no duplicate
loopback validation or raw rejected destination disclosure is introduced.

The worker loads only the identity helper and transport at startup; these
register handlers and make zero community requests until an explicit action.
The collector loads only on Preview. The UI module loads when sidepanel opens,
without collection/network/permission requests. Packaging explicitly includes
all four modules. They are all counted in named byte aggregates and line guards;
no existing per-file cap was raised and no minification was used.

Final measurements and test results are appended below after frozen validation.

## Reproduction and evidence

- `node extension/tests/community_transport.test.mjs`
- `node extension/tests/community_panel.test.mjs`
- `python scripts/check-architecture.py`
- `python -m unittest scripts.tests.test_architecture_graph scripts.tests.test_community_packaging scripts.tests.test_extension_checkout_bytes`
- `python scripts/audit-i18n.py --write-runtime`
- `PYTHONPATH=backend python scripts/test-backend-offline.py`
- `node scripts/community-capture-visual-acceptance.cjs --self-test`
- Hosted actual Edge: `node scripts/community-capture-visual-acceptance.cjs build/community-capture-ui`

Backend fixtures cover nonpersisting preview, sanitized memory/disk, immutable
selected save, delete/export/isolation, all bounds, malformed/NaN/extra fields,
unsupported identity, active-part mismatch, deletion/retry/expiry/replay,
concurrency, disable/clear and directory scope. Real HTTP admission plus real
caption processing proves exact source/part retention for both initial video
and subtitle-only requests with isolated storage and offline provider seams.
The old OpenAPI golden snapshot is unchanged; only the two independently tested
new paths and their three strict request schemas are excluded additively.

The rendered helper uses shipped DOM/sidepanel code in Edge with synthetic
Chrome/local replies. It checks realistic legacy/open-shadow shapes, author and
control decoys, hidden/offscreen/clipped/covered/partially visible text, traversal
bounds, literal hostile-looking text, unchecked selection, cancel/late responses,
source/permission changes, uncertain saves, keyboard focus and bilingual narrow
layouts. Failure evidence and screenshots go to the existing hosted artifact.

The helper's syntax/asset self-test is not rendering evidence. Live Bilibili DOM,
real account content, native installation/permission prompts and the paused
browser developer-mode warning are outside this synthetic gate. No live video
or account was accessed; no security warning was bypassed. Hosted screenshots
must be inspected before claiming rendered acceptance complete.

### Measured source/package bytes (baseline 575b968)

| Item | Before | After | Guard |
| --- | ---: | ---: | ---: |
| Complete capture-script inventory | 339,271 B | 355,525 B | 355,550 B |
| Separate, explicitly counted community UI module | 0 B | 7,253 B | 7,500 B |
| identity/origin helper | 0 B | 1,106 B / 22 lines | 30 lines |
| background transport | 0 B | 8,360 B / 100 lines | 135 lines |
| on-demand collector | 0 B | 6,738 B / 103 lines | 125 lines |
| sidepanel community module | 0 B | 7,253 B / 99 lines | 130 lines |
| Full package files, uncompressed | 620,798 B / 26 files | 659,350 B / 30 files | Explicit release whitelist |
| Deterministic comparison ZIP | 185,430 B | 197,835 B | Measurement only |

The complete capture inventory grows 16,254 B (4.79%). Worker startup parsing
adds 9,516 B including the 50-byte import change. Each explicit injection loads
7,844 B (helper plus collector). Sidepanel-only helper/UI parsing adds 8,359 B;
existing panel hooks/absent-source handling add 180 B, HTML 1,779 B, CSS 898 B, and bilingual runtime
fallback messages 5,562 B. These costs are disclosed separately rather than
calling all additions lazy-loaded. Unique capture+community-UI inventory is
362,778 B. The full package grows 38,552 raw bytes / 12,405 compressed bytes.
The comparison ZIP uses sorted release whitelist/locales/icons, fixed timestamps
and Python deflate level 6; it is not the Windows release artifact or a network
benchmark. LF checkout tests cover all four new modules.

Local frozen validation: 1,823 offline backend tests passed (20 existing skips),
269 script tests passed (3 existing skips), and all 76 extension test files
passed. Architecture, package/LF checks, bilingual locale audit, compileall and
hosted-helper syntax/asset self-test passed. The original OpenAPI golden fixture
is unchanged and the exact additive capture contract passes independently.
Hosted actual Edge screenshots and live/native acceptance remain separate gates;
no local self-test is presented as rendering evidence.

Review follow-ons retain uncertain Save status after an error/timeout path,
including close/reopen and navigation, until a fresh explicit action. The hosted
helper now observes actual click-handler promises and pending transport IDs,
releases held requests in finally, and waits for both settled states. Nine
injected fixture contracts verify original-error preservation through cleanup
and report failures, request-arrival/settlement order, and shipped selectors.

### Inline timestamp hit-test correction (2026-10-17)

Actual Edge run [38996866095](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38996866095)
on 67549d4 retained all five intended bodies but rejected the visible inline
`01:23` timestamp. In both the original and separate clear fixture, the element
and full-text Range had the same fractional right edge (60.046875 CSS pixels).
At the two right-edge sample points, `elementFromPoint` returned the containing
section while `elementsFromPoint` returned the timestamp span as its first item.
All five character centers hit the span. A genuinely covered final digit instead
returned the opaque covering element first from both APIs and remained untimed.
The screenshots and bounded diagnostics establish a native fractional-boundary
divergence on these fixtures, not a proven argument-rounding bug or live-site proof.
[Chromium's TreeScope implementation](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/third_party/blink/renderer/core/dom/tree_scope.cc)
uses floating-point hit locations for both APIs and distinct single/list result
paths; that source is explanatory context, not an exact Edge binary trace.

Only the timestamp caller now selects topmost-list hit testing. The existing
geometry, viewport/ancestor clipping, hidden/style checks and five coordinates
are shared unchanged. Each point accepts only the first list item when it is the
timestamp or a contained descendant. It never searches past an overlay, accepts
a parent/shadow host, or falls back when the list API is absent. General comment
and danmaku body visibility is unchanged. There is no production Range walker.
The original five-body and 83-second assertions remain; the representative fixture
also requires clear 83 seconds and rejects covered, hidden, offscreen and partially
clipped timestamps. Deterministic tests cover those failures plus unavailable APIs,
empty lists, ancestor clipping, and unchanged body behavior. Actual hosted Edge
acceptance for the corrected tree is still required.

Compared with 67549d4, this correction adds **185 actual bytes** only to the
on-demand collector (6,553 to 6,738 bytes; 99 to 103 lines). The reviewed aggregate
cap rises by **50 bytes**, from 355,500 to 355,550; actual inventory is 355,525.
All per-file line caps, the separate UI byte cap, and eager startup/sidepanel costs
remain unchanged. Package size increases by 185 raw bytes and 38 deterministic
ZIP bytes. The branch shares visibility checks rather than duplicating them;
no code compression or inventory omission is used to meet the budget.

### Accepted-task revocation correction (2026-10-17)

Actual Edge run [38998203703](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38998203703)
on 67dda14 passed the complete DOM gate, including original/representative clear
83-second timestamps and covered/hidden/offscreen/partial negatives. The first
Chinese 390-pixel panel case passed preview, selected save, stale navigation,
held cancellation/save, and Escape before revocation exposed a null-identity
exception in the existing sidepanel's `sourceContinuityKey` during `renderContext`.
The saved task correctly remained available while page identity was cleared.

The continuity helper now maps only absent (`null`/`undefined`) identity to an
empty sentinel; valid source keys remain byte-for-byte unchanged. This cannot
match an active prior source or reuse its context. The other legitimate cleared
source caller is an in-flight quick-Q&A current-source check; preflight/handoff/
progressive starts retain their existing valid-source admission and epoch guards.
The shipped-path regression accepts a task, mounts the actual community module,
revokes, and verifies preview cancellation, cleared identity/cues/preflight,
disabled sending and continued access to the accepted task. Repeated revocation
does not request a grant or recollect. Held Q&A answer/error results settle without
repainting the cleared source. The test harness retains multiple runtime listeners
like Chrome, so it does not hide either module's revocation listener.

This correction adds 30 bytes to `sidepanel.js` (78,564 to 78,594; 1,516 to 1,517
lines), with every cap unchanged. It does not change eager worker or on-demand
collector bytes. Compared with 67dda14, the same 30-file package grows 30 raw bytes
and 10 deterministic ZIP bytes. All four screenshots retained by that run were
inspected; the remaining bilingual/wide panel cases still require actual hosted
acceptance after this correction. No live site or model call is implied.
