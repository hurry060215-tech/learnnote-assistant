# Design baseline review — 2026-10-12

## Evidence and scope

Reviewed actual Windows Edge screenshots from UI artifact `11730616041`, produced
at commit `1af260dcdb59bc7ed7aab8d7d827bfa90bcaf0c7`, Edge `153.0.4234.48`.
The `web/` tree is identical to audit base
`2424251996aa31dd668d0691773e86f8368aa2a8` (`git diff` is empty for that path).
Artifact ZIP SHA-256:
`18d7c2575792abe1361a063741db90567dec89ae5c6d8cadef561aaa497b6b4f`.

These are **before-fix** screenshots, not evidence that the changes below passed.
The runner's fixtures are synthetic and the backend is isolated. The review used
viewport crops of the original full-page captures so text was inspected at normal
size. Original screenshots were not modified.

Inspected: `product-ui/home.png`, `settings-model.png`, `settings-notes.png`,
`assistant-mobile.png`; `study-product-ui/reader-{1440,768,390}-100-{light,dark}.png`
representative light/dark captures, `studio-390-100-light.png`, and the normal dark
create-dialog capture. The older artifact does not establish every combination of
1280px and sidebar states. Do not present it as a complete requested matrix.

## Findings and narrow fixes

1. **Hidden mobile navigation leaves a visible shadow.** In the 390px reader and
   assistant, a gray band intrudes from the left even though the drawer is closed.
   The mobile `.sidebar` retains its 90px blur while positioned offscreen. Move the
   existing shadow to `body.menu-open .sidebar`; preserve the opening transition.
2. **Sidebar footer labels are crowded.** The visible “我的 / 学习空间 / 设置” labels
   compete for narrow tracks while the fixed five-column grid includes a hidden
   review control. Let visible controls use their content width, wrap if needed,
   and place the theme button at the trailing edge. No navigation is removed.
3. **390px assistant header has a broken title.** “全局助手” wraps while source scope
   and four controls share one row. Keep title and actions on the first row and
   give the source label its own second row. Preserve all controls and body text.

No new palette, type family, imagery, card system, or motion language was chosen.
Current reader text remains left aligned within a centered, opaque content area.
The home title, input, section titles, and list share a clear left edge. Dialogs
retain a centered surface with consistent bounded content. A later pass should
assess annotation/reader inset differences and the 768px density against the
user's actual reference images rather than introduce speculative changes.

The first new Edge run also exposed a pre-existing sidebar accessibility defect:
opening a note left the desktop sidebar visible but unconditionally changed its
toggle to `aria-expanded="false"`. The new matrix then correctly failed when a
click based on that state collapsed the visible sidebar. Remove the two obsolete
sidebar writes in `openItem()`; `installInteractions()` already handles the
selection event, preserving desktop state and dismissing/inerting the mobile
drawer. Keep the original toggle assertion and add a post-selection check for the
desktop/mobile ARIA and inert state. This is a product-state fix, not a timeout or
weakened test assertion.

## Design documentation

The old `docs/design/README.md` described navy/teal, 12px controls, and a different
navigation model. That is inconsistent with the current neutral green-gray
workspace and 7px controls. Mark it archived and make root `design.md` the current
contract. Root `AGENTS.md` requires every new UI page/component to follow it.

The reference repository's design workflow and the Kole Jain resource index were
read. User screenshots have not arrived and their appearance has not been assumed.
The root contract is explicitly reference-pending.

## Verification boundary

The current cloud Chromium process cannot launch because its Unix socket/IPC call
is denied by the environment. No permission changes or sandbox bypass were used.
New post-fix pixels and geometry must come from the supported actual Edge job.

`scripts/design-visual-acceptance.cjs` captures 64 viewport PNGs over 1280/1440/768/390,
light/dark, open/closed navigation, home/reader, empty search/assistant, create,
and appearance settings, plus two 195x422 CSS-pixel assistant captures for effective
200% reflow (not native browser zoom). The narrow header stacks and action controls
wrap; the panel can scroll to keep the composer reachable. It uses actual application clicks with one synthetic
Markdown import, scoped list/history reads, and no external model traffic. The
report separates browser interaction, fixture data, screenshots, and geometric
assertions. It does not assign aesthetic scores or claim native desktop WebView
coverage. The existing study-product acceptance gate remains responsible for its
zoom/reduced-effects/accessibility workflow matrix.

Before approving the patch, run the new Edge capture and inspect its PNGs. Confirm
the three visible defects are resolved, text stays readable, controls remain
usable, and no new clipping or imbalance appears. Geometry checks alone do not
complete visual review.

Local checks completed: JavaScript syntax for the new capture runner,
`git diff --check`, and the full scripts test suite (175 tests, 3 skipped), including
the six UI visual contract tests and the architecture budget guard. Removed only
previously overridden/repeated CSS declarations to retain the existing 2310-line
runtime CSS budget; the guard was not relaxed.
The new browser runner has not run locally because of the verified IPC limit.
