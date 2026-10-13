# LearnNote design contract

Status: **user-authorized reading refinement; visual reference images pending**.
This document records the quiet reading workspace and its hierarchy refinements.
The current direction is deliberate subtraction: reading first, concise review
status, discoverable secondary tools, and one coherent assistant empty state.
It does not adopt a new theme from an unseen reference image. Review actual reference pixels before changing
the palette, type family, composition, or visual identity.

Every new page, dialog, navigation item, and component must follow this contract.
Read it before UI work and update it in the same change as an intentional token
change. Prefer the existing component and semantic color variables over adding a
second style system.

## Scope and intent

The main app is `web/index.html` and **only** `web/desk.css`; appearance preferences
come from `web/reading-settings.js`. `web/classic.html`, the public `site/`, and the
browser extension are separate surfaces. Do not load their styles into the main
workspace. Earlier images under `docs/design/` are archived concepts, not current
pixel acceptance baselines.

LearnNote is a quiet local study workspace. Starting a note, reading it, verifying
its source, and adding personal understanding are the primary tasks. Preserve
left-aligned body text, legible hierarchy, useful state transitions, and a balanced
reading column. Symmetry means equal insets and coherent alignment within the
available workspace; it does not mean centering paragraphs or ignoring an open
sidebar.

## Colors

Use the semantic variables below. Hex values are opaque unless alpha is explicit.

| Role / CSS variable | Light | Dark |
| --- | --- | --- |
| Canvas `--bg` | `#FFFFFF` | `#1E1E1E` |
| Navigation / secondary surface `--panel` | `#F5F6F3` | `#252525` |
| Opaque reading surface `--paper` | `#FFFFFF` | `#1E1E1E` |
| Primary text `--ink` | `#26332C` | `#ECEEE7` |
| Secondary text `--muted` | `#58635D` | `#BBC3CF` |
| Divider / control border `--line` | `#E3E7E2` | `#3A3A3A` |
| Neutral accent `--accent` after preferences initialize | `#303832` | `#D5D9D6` |
| Selection / hover surface `--tint` | `#EDF2EB` | `#303030` |
| Destructive / error text `--danger` | `#A13A2C` | `#FFAAA0` |

The stylesheet's pre-initialization dark accent fallback is `#B5D0A5`.
`applyReadingAppearance()` sets the effective neutral accent to `#D5D9D6`.
Do not confuse the fallback with the initialized appearance.

Supported user accent pairs, light / dark:

| Preference | Light | Dark |
| --- | --- | --- |
| Neutral (default) | `#303832` | `#D5D9D6` |
| Teal | `#087B83` | `#81D6D5` |
| Blue | `#4057A0` | `#ABBDFF` |
| Plum | `#79516F` | `#D9AED0` |

Use accent for primary actions, selected navigation, focus, and source links.
Primary buttons use `--accent` background and `--bg` text. Do not introduce a new
accent or turn muted text into low-opacity primary text. Existing specialist
colors (`#25897A` timeline completion, `#A05B2A` waiting route text, `#687C65` usage
meter, `#151515` video canvas) are exceptions to audit for contrast, not new palette
tokens to copy. Status must also have text or a shape cue.

## Typography

UI and default reading sans share `--ui-font`: `"Noto Sans SC", "Noto Sans CJK SC",
"PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", system-ui,
sans-serif`. Chinese-capable families precede the Latin system fallback. No remote
font download is required. Serif/mono remain explicit reader preferences. Font
rendering can differ by OS; the visual gate records actual platform fonts for
Chinese/mixed body text and UI labels through Edge DevTools. A CSS stack alone
is not proof that those fonts rendered. Do not reuse the website's limited
character subset for arbitrary user notes.

| Role | Size | Weight | Line height |
| --- | --- | --- | --- |
| UI body | 15px | 500 | 1.55 (23.25px) |
| Body paragraph outside reader | 15px inherited | 500 | 1.8 (27px) |
| Button / select | 14px | 600 | 1.55 (21.7px) |
| Form label | 14px | 600 | 1.55 (21.7px) |
| Supporting text | 13px | 500 | inherited; settings use 1.55 |
| Compact metadata / eyebrow | 12px | 500 | 1.55 (18.6px) |
| Home title | 30px desktop; 25px at <=760px | 600 | 1.35 |
| General dialog h2 | 23px | 700 (browser h2 default) | 1.6 |
| Tools dialog h2 / settings section h3 | 20px | 700 | 1.6 |
| Home section h2 | 17px | 650 | 1.6 |
| Reader body | 17px default | 500 default | 1.65 (28.05px) |
| Reader h1 | `clamp(24px, 2.1vw, 30px)`; 27px at <=760px | 700 | 1.35 |
| Reader h2 | 22px | 650 | 1.6 (35.2px) |
| Reader h3 | 18px | 650 | 1.6 (28.8px) |
| Reader code | 14px, Consolas / monospace | 400 in blocks | 1.5 in blocks |
| Assistant answer | 15px | 500 | 1.65 (24.75px) |

Reading preferences remain authoritative: sizes 15/16/17/18/20px; weights
400/500/600; line heights 1.65/1.85/2.1; widths 760/940/1120px; sans/serif/mono.
Use `--reader-size`, `--reader-weight`, `--reader-leading`, `--reader-width`, and
`--reader-font`; do not hard-code a new page around the default only.

Title, body, and metadata must be distinct. Do not make all content bold to create
hierarchy. Body paragraphs, forms, note rows, and explanations align left. Center
only short controls or numeric comparisons when their component requires it.

## Spacing and layout

Use this baseline vocabulary when adding spacing. These names describe existing
values; they are not yet CSS custom properties. Do not mass-replace the existing
CSS before the reference review.

| Token | Value | Use |
| --- | --- | --- |
| space-1 | 4px | tightly related controls / metadata |
| space-2 | 8px | compact control groups |
| space-3 | 12px | normal control and field relationships |
| space-4 | 16px | grouped content / narrow surface insets |
| space-5 | 20px | section content |
| space-6 | 24px | surface padding / section separation |
| space-8 | 32px | wide reading inset / dialog padding |
| space-10 | 40px | legacy intermediate reading inset |
| space-12 | 48px | annotation inset on wide screens |
| space-16 | 64px | desktop home offset below toolbar |

Existing optical values such as 7px icon gaps, 9px button block padding, 10px
sidebar gaps, and 14px sidebar insets remain component-specific. Reuse the
component rather than making a new general spacing scale from every literal.

- Sidebar: 232px default, user resizable between 200px and 420px where room
  permits. At <=760px it is a 264px overlay. A closed mobile sidebar has no shadow.
- Sidebar padding: 22px top, 14px inline, 12px bottom. Footer controls size to their
  content and can wrap; the theme control sits at the trailing edge. Hidden
  controls must not leave fixed empty grid tracks.
- Toolbar: 72px high, 24px inline padding; narrow viewports use a 62px minimum and
  10px inline padding. Workspace container queries allow controls to wrap when a
  panel narrows the main column.
- Home: max-width 860px with 32px inline inset, centered within the workspace;
  64px block margin. At <=760px use 18px inline inset and 24px block margin.
- Reader: max-width 940px by default, centered within the workspace. Wide reading
  inset is 24px block / 32px inline; <=1250px uses 30px; <=760px uses 24px / 18px.
  The workspace container query at <=720px sets 20px inline reading insets.
  Outer reading gutters are 24px, then 16px at <=1250px, then 10px at <=760px.
- Annotation, personal review, and editor widths follow `--reader-width`. Body,
  review summary, and annotation content share the same inline insets at every
  breakpoint. Personal review defaults to a 44px summary plus one concise, visible
  truthfulness boundary. Details and explicit mark/revoke/refresh actions expand
  only on request; navigation resets the disclosure, polling does not.
- Assistant: 430px default; 320–720px user range within available room. Above
  1100px it reserves main-column space; at <=1100px it overlays. At <=760px it is
  full width. At assistant-container widths <=600px, including desktop side panels,
  the header puts the source label on a separate second row. At container widths
  <=360px the header uses one column and actions wrap. At viewport widths <=360px
  the panel can scroll so controls remain reachable at narrow effective zoom.
- Desktop page contents appears only when the width and `data-contents-fit` allow
  it; do not reserve an empty column when hidden.
- General dialog: min(540px, viewport minus 28px), maximum 90dvh, 32px padding;
  24px padding at <=760px. Settings is a larger scrolling workbench with a fixed
  header/footer, not a scaled version of the general form dialog.

Within a surface, related headings, body, fields, and rules should share an edge.
For new pages use equal left/right outer insets. Keep long text readable when both
side panels are open; hide or wrap secondary controls before compressing prose.

## Components: shape, border, and elevation

| Component | Radius | Border | Shadow |
| --- | --- | --- | --- |
| Button / input / select / textarea | 7px | 1px; transparent button default, `--line` field border | none |
| Note navigation row | 7px | none | selected button: inset 2px 0 `--accent` |
| Settings navigation item | 7px | transparent | none; selected `--tint` fill |
| Common status / code / study card | 8px | 1px `--line` where bounded | none |
| Source / source inspector | 10px | 1px `--line` | none; pinned source: 0 8px 24px `#00000011` |
| General dialog / bounded grouped card | 12px | 1px `--line` | dialog: 0 24px 100px `#00000022`; card: none |
| Profile dialog / home URL composer | 16px | 1px `--line` | composer: 0 3px 14px `#00000005` |
| Source chip | 999px | 1px `--line` | none |
| Tabs container | 8px | none | active tab: 0 1px 4px `#00000011` |
| Mobile sidebar when open | 0 | trailing 1px `--line` | 20px 0 90px `#00000022` |
| Assistant at <=1250px | 0 | leading 1px `--line` | -20px 0 70px `#172B4020` |
| Reader / annotation surface / recent-note row | 0 | dividers only | none |

Buttons use 9px block / 13px inline padding by default; compact actions reuse
their existing component. Primary hover retains the accent and applies brightness
1.12; secondary hover uses `--tint`. Disabled opacity is 0.55. Keyboard focus is a
2px `--accent` outline, offset 3px. Do not remove focus to improve screenshots.

Use one main action per task area. Keep destructive controls secondary and labeled.
The top reader toolbar keeps editing, source, and assistant access. The utility
strip keeps source state and contents visible, with export, learning tools,
typography, frame index, versions, and focus mode in a native “更多操作” disclosure.
There is one edit entry. The disclosure closes on selection, outside pointer, or
Escape; Escape returns focus, and dialog actions inherit a visible return target.
The assistant's empty explanation and dismissible suggestions share the history
surface. Sending begins a regular history; hidden/dismissed preference state is
preserved. The composer has one 2px focus ring, never competing inner/outer rings.
Keep processing details collapsed and visually secondary; warnings stay visible.
Empty states name the missing content and give a relevant next action; keep them
within the same surface grid. Avoid adding decorative cards around every line.

## Motion and accessibility

Preserve the motion that communicates state:

- Button/background/border/shadow hover: 140ms ease.
- Disclosure chevron: 150ms ease.
- Mobile sidebar left position: 180ms.
- Dialog entry: 120ms ease-out, from translateY(7px) scale(0.99).
- Backdrop entry: 160ms ease-out; `#15151555`, blur 3px.
- Assistant working dots: 1.2s ease-in-out with 160ms stagger; text accompanies it.

`prefers-reduced-motion: reduce` disables motion and smooth scrolling. Reduced
transparency uses an opaque `#F5F6F3` light / `#252525` dark backdrop. Reading,
transcript, form, code, and table surfaces stay opaque. No information relies only
on color, blur, or animation. Check readable text at >=4.5:1 contrast and large
text / essential graphics at >=3:1. New touch controls target 44px; current compact
controls require a dedicated accessibility pass rather than an unreviewed global
resize.

## Required visual review

Run `node scripts/design-visual-acceptance.cjs http://127.0.0.1:8765 build/design-ui`
against an isolated local fixture backend with actual installed Edge. It records
1280, 1440, 768, and 390px at light/dark with the note sidebar open/closed; captures
home, populated reader, empty search, empty assistant, create dialog, and settings;
and checks horizontal overflow, reader centering, footer bounds, the hidden drawer
shadow, and assistant header wrapping. Four additional assistant captures use
195x422 CSS pixels for effective 200% reflow of a 390x844 area; this is not native
browser zoom. Actual wheel input reveals the empty-history explanation and
composer; both scroll positions are captured in each theme (68 PNGs total).
View the PNGs. Geometry assertions are not
an aesthetic approval. The existing study-product gate separately covers effective
200% viewport scaling, reduced effects, forced colors, and source workflows.

For changes, compare before/after with the same fixture and preferences, inspect
title/body hierarchy, equal gutters, optical balance, button alignment, dialog
headers/footers, open/closed panels, empty/loading/error states, focus, and motion.
Validate Close/Cancel/Escape and repeated navigation. A full-page screenshot alone
is insufficient: inspect viewport captures at readable size. Report missing
widths/states and browser limits explicitly.

## References and next decision

- [Distinctive AI Design](https://github.com/houxin0010/distinctive-ai-design): use
  the existing product constraints, inspect running screenshots, and limit each
  refinement round to the most important problems.
- [Kole Jain, Every UI Concept](https://www.kolejain.com/resources?scrollTo=every-ui-concept):
  reference selected by the user. The resource index was read; final visual
  interpretation awaits inspected reference pixels and the user's screenshots.
- [Baseline audit and evidence](docs/qa/20261012-design-baseline.md).

When reference images arrive, inspect them first, identify the exact transferable
rules, and revise this document with the chosen direction. Do not infer a new
theme from a resource title or claim the pending screenshots have been reviewed.
