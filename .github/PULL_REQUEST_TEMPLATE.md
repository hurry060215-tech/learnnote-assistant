## Summary

Describe the user-visible problem, the scope of this change, and why this
approach fits LearnNote's desktop-first, local-first architecture.

## Changes

- Describe the focused implementation changes.

## Validation

List exact commands and results. Include desktop and mobile screenshots for UI
changes, and a redacted source matrix for current-page media changes.

```text
Not run / command and result
```

## Product and data impact

- [ ] The local backend still binds to `127.0.0.1` by default, or the changed
      trust boundary is explicitly documented.
- [ ] The data directory remains user-configurable; this change does not
      hard-code a developer-specific drive or path.
- [ ] Cookie/page evidence collection remains user-triggered and sensitive
      values are redacted from logs, diagnostics, fixtures, screenshots, task
      files, and exports.
- [ ] The change does not record browser tabs, bypass DRM/access controls,
      grant unauthorized download access, complete lessons, or fabricate
      progress.
- [ ] Generated notes and status messages distinguish observed evidence,
      fallback output, skipped work, and failures.
- [ ] Remote API/model data flow and retention implications are documented, or
      this change sends no new data remotely.

## Dependencies and distribution

- [ ] No dependency, bundled binary, browser permission, network destination,
      or installer behavior changed.
- [ ] Or: all such changes are described below, licenses were verified, and
      `THIRD_PARTY_NOTICES.md` plus release packaging were updated as needed.

Details:

## Checklist

- [ ] I added or updated focused tests for the success and failure paths.
- [ ] I did not commit secrets, authenticated URLs, browser data, private
      course content, user task artifacts, model caches, or generated builds.
- [ ] I updated user/developer documentation where behavior changed.
- [ ] I kept unrelated refactors and formatting out of this PR.
- [ ] I have the right to submit this contribution under Apache-2.0.
