# Executable updater platform boundary (#70)

The current release installer is Windows-only. Desktop and HTTP entry points now
reject client executable download/apply on macOS and Linux before network,
filesystem, thread, rollback or process effects. Release information and the
existing managed browser-extension flow remain available. No new updater,
package, permission, release asset, signing or notarization behavior is added.

The update center follows explicit capabilities, including when a copied Windows
receipt says `ready`. It explains manual updating through official release/deploy
instructions and retaining the selected data directory. The classic UI also shows
the returned manual guidance. Windows checksum, owned-installer, task/edit and
duplicate-click protections remain in place.

## Evidence and limits

- Offline contracts cover darwin/linux/win32 status, backend/degraded bridge
  responses, legacy checks, blocked entry points, HTTP intents/actions, stale
  ready receipts, guarded click handlers and Windows behavior.
- Existing `scripts/update-center-acceptance.cjs` hosted Edge gate now captures
  macOS/Linux capability fixtures at 1280/390 pixels and checks manual guidance,
  disabled download preference, hidden executable actions, repeated navigation,
  and programmatic hidden-button activation without real installers.
- Local screenshot execution is unavailable in this cloud checkout: Playwright is
  not installed in the available Node package tree. Hosted Edge screenshots still
  require execution and pixel review; browser fixtures do not prove native
  macOS/Linux/Windows installation or actual platform UI behavior.
- No live update downloads, external model calls, real user data or installers
  are used by these tests.
