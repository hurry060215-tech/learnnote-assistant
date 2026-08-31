# LearnNote workspace design specification

These images are the visual acceptance references for the v0.2 experience
overhaul. They preserve the existing local-first workflow while making the
first useful note, evidence state, and next action visible earlier.

- `workspace-desktop-v0.2.png`: library, note editor, synchronized evidence.
- `workspace-mobile-v0.2.png`: first-run capture and progressive draft state.

## Product hierarchy

1. The primary task is to start or resume one learning note.
2. A subtitle-grounded outline becomes readable before deep visual analysis.
3. Each important claim exposes its evidence type and source locator.
4. Export and study-card actions are secondary to reading and verification.
5. Local-first status stays visible without adding an account or cloud model.

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

The first-run screen may show only the LearnNote brand, `从一段视频开始`, one
short progressive-generation explanation, the three source choices, the
local-first privacy line, an active draft state, and the five navigation labels.
Technical implementation names such as FFmpeg, yt-dlp, or Whisper belong in
diagnostics and advanced settings, not in the primary workflow.
