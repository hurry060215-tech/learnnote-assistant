# v0.2.9 UI acceptance

Validated on 2026-09-14 against the local workbench and an isolated source server.

## Interactive walkthrough

- Opened all eight settings sections, model route details, appearance previews and profile.
- Opened courses, course sources, review cards and answer reveal without rating real cards.
- Switched video, file and browser inputs without submitting real model work.
- Opened a real completed video note, its outline, versions, export choices, learning tools and global assistant.
- Checked updated typography in the browser, then verified light/dark and mobile screenshots with isolated sample content.

## Changes

- Default reading leading 1.85 → 1.65; clearer secondary text; independent 400/500/600 reader weights and compact/bold presets.
- Reduced paragraph, list, settings and dialog spacing. Kept user-selected appearance values until explicitly changed.
- Consolidated sidebar footer into a stable grid. Review opens a daily overview; plan editing is collapsible.
- Collapsed model route information and older assistant history. Historical messages show their creation dates.
- Corrected saved model readiness and remote-network descriptions. Official update metadata can recover from GitHub API throttling.

## Automated evidence

- Backend: 571 tests passed. Web: 58 tests passed. Desktop: 45 tests passed. Release scripts: 60 tests passed.
- Browser checks passed for assistant navigation/streaming, resizing/video layout, reader workflow, settings recovery, history/drafts, core output, update controls, product workspace, unified workspace and redesign interactions.
- New `scripts/ui-readability-acceptance.cjs` checks every settings section, persisted weight/leading, import/edit/outline, review overview, dark contrast and mobile overflow. Added to CI.

The walkthrough did not submit paid AI requests, delete user material, alter credentials, download optional models, or resubmit the extension. Destructive/update behavior is exercised in isolated tests. This report does not claim a fresh model-quality evaluation of every video.

The extension source remains identical to the submitted 0.2.8 source at commit `5225587`; only the client release advances to 0.2.9.
