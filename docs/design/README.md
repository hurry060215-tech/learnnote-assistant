# LearnNote workspace design specification

These images are visual acceptance references, not screenshots of a released
build. The v0.3 clarity pass removes the remaining control-panel structure so
that starting a note and reading it become the two obvious paths.

- `workspace-desktop-v0.2.png`: library, note editor, synchronized evidence.
- `workspace-mobile-v0.2.png`: first-run capture and progressive draft state.
- `workspace-desktop-clarity-v0.3.png`: quiet four-destination navigation,
  compact library, immediate note body, and one evidence drawer.
- `workspace-mobile-clarity-v0.3.png`: visible URL composer, two compact source
  shortcuts, and a persistent background-task strip.

## Product hierarchy

1. The primary task is to paste a source and generate a note in one action.
2. The note body appears before diagnostics, coverage charts, and export tools.
3. Evidence is one compact trust summary until the learner asks to inspect it.
4. Tasks are background state, not a top-level destination beside the library.
5. Export and review are secondary to reading and verification.
6. Local-first status stays visible without adding an account or cloud model.

## Design tokens

The implementation may tune exact values for contrast, but it must keep this
system coherent:

- background: true white and cool neutral gray;
- text: dark navy, with one muted blue-gray tier;
- accent: LearnNote teal, reserved for primary actions and evidence;
- borders: fine cool-gray lines, never decorative heavy frames;
- radii: 12px controls and 16px elevated surfaces;
- spacing: an 8px base scale;
- motion: short state transitions only, disabled by reduced-motion settings;
- typography: system Chinese UI fonts with explicit control and reading sizes.

## Glass boundary

Restrained translucent surfaces are allowed for the app header, compact
navigation, progress sheet, floating toolbar, and evidence inspector. Long-form
notes, transcripts, code, formulas, tables, and settings forms stay on opaque
surfaces. A readable opaque fallback is required when `backdrop-filter` is not
available or the user requests reduced transparency.

## Responsive and accessibility gates

- All five mobile destinations are visible at once with icon and text.
- The bottom navigation respects safe-area insets and never scrolls sideways.
- Touch targets are at least 44px; desktop focus indicators remain visible.
- At 200% zoom the primary action, draft state, and cancel action stay usable.
- No information is encoded only by color, blur, animation, or iconography.

## Above-the-fold copy contract

The first-run screen may show only the LearnNote brand, `从一段内容开始`, one
short progressive-generation explanation, a URL composer with its primary
button, two compact source shortcuts, one document-import link, the local-first
privacy line, an active draft state, and the four navigation labels.
Technical implementation names such as FFmpeg, yt-dlp, or Whisper belong in
diagnostics and advanced settings, not in the primary workflow.

## Interaction acceptance

- At 390 x 844 the URL input and `生成笔记` button are both visible without
  scrolling.
- A normal public URL creates a task after one primary-button click. A separate
  confirmation screen appears only for missing tracks, authorization, DRM,
  ambiguous candidates, or an explicitly chosen custom template.
- Opening a completed note shows its first paragraph in the upper half of the
  desktop viewport. At most one compact trust summary precedes the body.
- The primary navigation contains `开始`, `资料库`, `复习`, and `设置`. Running
  and failed tasks surface inside a global task strip and library filters.
- A library row opens on click. Destructive actions live behind an overflow
  menu and never compete with the reading action.
- Glass is reserved for navigation, compact task state, and evidence overlays;
  the long-form reading surface remains opaque and high-contrast.
