# Native optional-host acceptance gate

Implementation status: native acceptance is **unmet**. Issue #135 remains open.
The Linux authoring environment has no native Windows desktop. Local
unit/contract tests and the automatic real extension/media smoke are not a
native permission acceptance result.

The first hosted run on commit `81b4696e3a126230b0c84f7e74bca0aaac06cbe8`
([run 38942622524](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38942622524))
passed the existing real extension/media smoke but stopped before optional
permission prompts. The correct native LearnNote toolbar control did not expose
`InvokePattern`. Inspection of its native-window screenshot also confirmed
Edge's “Turn off extensions in developer mode” security warning. It was not
dismissed or bypassed. Native permission scenarios therefore remain unexecuted,
not failed product-permission assertions. The driver now explicitly stops on
that visible warning and includes supported UI Automation patterns in evidence.
The [retained artifact](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38942622524/artifacts/12063932497)
contains the original native tree, screenshot and blocker report.

## Reproduction and scope

The native gate is isolated in `native-permission-acceptance.yml`, with only an
explicit `workflow_dispatch` trigger, read-only repository permissions and a
15-minute budget. It is never dispatched automatically; the existing automatic
UI visual extension/media smoke is unchanged. A manual dispatch does not permit
dismissing a security warning, and a blocked native run fails rather than being
reported as a pass or an ignored failure. Review its exact commit and native
evidence before claiming acceptance.

The command is `python scripts/extension-permission-acceptance.py`, with installed
Windows Edge and the repository's constrained backend test dependencies. The
current cold hosted Edge setup shows a browser security warning and is not a
completed acceptance environment. Continuing requires a human-controlled,
suitable browser setup where the person handles any security decisions, or a
separately reviewed store-installed setup. This harness does not silently switch
to a real user's profile, install a store build, accept the warning, or change
security settings/flags to avoid it. Store-installed validation must verify the
exact installed version/source and remains separate from this unpacked gate.

Each decision starts with its own fresh profile. Each
profile is then restarted once for persistence checks and removed after Edge
closes. The backend data and synthetic samples are also disposable.

The exact unpacked extension is used without a manifest change. Browser-local
resolver rules map only `learnnote-permission.test` and
`learnnote-ungranted.test` to `127.0.0.1`; neither is a required manifest host.
There are no hosts-file, registry, global browser, or real-user-profile changes.
No sandbox/security bypass, permission autogrant, mocked `chrome.permissions`,
or user-gesture override is used.

Windows UI Automation identifies controls only in the spawned browser process,
excluding web-document subtrees. It invokes the extension action through the
native toolbar and selects uniquely matched Allow/Deny controls only when the
native permission text identifies LearnNote and the exact synthetic host. It
saves the selected control, native control tree and native-window screenshot.
If those controls cannot be identified, the gate fails with a blocker instead of
switching to blind clicks or mocked permission state.

The scenario asserts:

- Fresh profiles have neither test-origin nor blanket host permission.
- Initial denial is a real native prompt and creates no backend task.
- Initial allow is a real native prompt and creates one deferred quick-mode
  handoff in the real isolated backend, without starting downloads/model work.
- Only the authorized host's seeded synthetic cookie is readable. A second
  seeded origin remains ungranted.
- The product's Revoke control calls the real permission API; the real
  `permissions.onRemoved` event occurs and previously populated memory/page/
  capture/persisted site caches are empty afterward.
- Closing the old source tab removes the temporary `activeTab` context. New-tab
  cookie inspection, preflight and task messages are rejected by the real
  background listener before reauthorization, with no new backend task.
- Restarting Edge preserves denial/revocation. A fresh explicit product action
  can authorize the site again and make a new handoff.

Reauthorization deliberately records whether a new native prompt appeared.
Chromium treats extension-initiated `permissions.remove()` as a soft revocation
and can reuse its previously granted permission after another user action. See
the [Chromium permission implementation](https://github.com/chromium/chromium/blob/main/extensions/browser/api/permissions/permissions_api.cc),
especially `RevokeOptionalPermissions` and the previously-granted check in
`PermissionsRequestFunction::Run`. Reused permission is not labeled a new
consent dialog.

## Remaining acceptance boundaries

This gate does not establish store installation/upgrade, browser-settings hard
revocation, Chrome-specific UI behavior, or access to real account/media sites.
Those remain separate evidence requirements for issue #135. The script's report
records this exclusion list and the exact manifest hash, extension version and
actual Edge version. Browser profiles are never uploaded as artifacts.
