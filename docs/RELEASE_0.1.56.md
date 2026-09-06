# v0.1.56 release candidate — 2026-09-06

## Included

This candidate incorporates the repository audit fixes and learning/UI changes recorded in IMPROVEMENTS_20260906.md and CHANGELOG.md. It preserves local-first, user-triggered browser capture.

The final pass also fixes cancelled Future execution and worker termination, rejects submissions to stopped queues, propagates Windows build/signing errors, and adds the missing local ASR runtime to the frozen Windows dependency lock. Source bootstrap continues to keep ASR optional; packaged Windows builds include it. Model weights are downloaded separately.

Version 0.1.56 is synchronized across backend, browser extension, installer fallback, Docker defaults, release notes and website download targets. Web cache tokens are refreshed.

## Verified locally

- Backend: 443 tests pass with the final ASR-enabled environment.
- Release/scripts: 57 tests pass; desktop launcher: 24 tests pass.
- All 8 web and 47 extension test files pass.
- Stage audit passed; 23 Windows workflow script blocks parse successfully.
- Dependency consistency: pip check passes.
- Browser learning acceptance: full document/code reading, review source access, progress and mobile layout pass; code contrast 10.9989:1; no page errors.
- Rebuilt Windows executable: file/product/API version 0.1.56; real WebView2 at 1424×861 has no horizontal overflow or page errors.
- Packaged health reports local ASR, ffmpeg and yt-dlp available. This verifies runtime availability, not downloaded model weights or real speech accuracy.
- Release-tree audit passes, including extension allowlist, bundled assets and license checks.

## Release gates still pending

This is a locally validated candidate, not a claim that all roadmap issues are closed. The issue-by-issue remaining scope is in IMPROVEMENTS_20260906.md.

Formal publication requires the repository PR review/checks and tagged release workflow. Inno Setup is not installed on this machine, so no new installer or install/upgrade test is claimed here. Signing, store submission, logged-in site acceptance, downloaded-model ASR accuracy and non-Windows native checks remain pending. The public latest release remains v0.1.55 until those gates complete.

Local candidate artifacts are under build/release-v0.1.56 (ignored by Git). The portable ZIP contains application files only; isolated test data remains outside its package tree.
