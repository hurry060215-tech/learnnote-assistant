# macOS signing and notarization setup

This maintainer guide describes the optional signing path in
[`.github/workflows/macos-release.yml`](../.github/workflows/macos-release.yml),
including the final-archive ordering correction in `bae1e97`, reviewed on
2026-10-16. Apple and GitHub references below were checked on that date. Recheck
the actual workflow and official guidance before using credentials or
distributing a build.

**Configuration instructions are not release acceptance.** This documentation
does not establish that signing credentials exist, that notarization has run,
or that a downloadable asset passes Gatekeeper. The corrected signed pipeline
has not been executed as part of this review. No credentials, Apple agreements,
security settings, workflow dispatches, tags, or release assets are changed by
this documentation.

## Unsigned acceptance remains separate

The browser-first source launch and isolated unsigned native acceptance do not
need an Apple distribution identity. Use the existing
[platform support matrix](PLATFORM_SUPPORT.md) for demonstrated coverage and
remaining requirements. A source-built or ad-hoc-signed application can exercise
native behavior without establishing Developer ID distribution trust; the
workflow's word "unsigned" means no configured Developer ID signing/notarization
path, not a promise that every packaged executable has no signature of any kind.

The [native platform acceptance workflow](../.github/workflows/native-platform-acceptance.yml)
is separate from the release workflow, has read-only repository permissions, and
does not use signing secrets or publish releases. Its synthetic app-launch and
data tests do not prove downloaded-asset Gatekeeper behavior, notarization,
credential migration, extension pairing, or every CPU architecture. The
[version rollback gate](QA_NATIVE_VERSION_ROLLBACK.md) and migration evidence
retain their own acceptance status; this guide does not promote them. Unreviewed
same-platform absolute-path relocation/mapping remains unsupported, as described
in the [task-path boundary](qa/20261016-task-path-portability.md).

Do not disable Gatekeeper, remove quarantine attributes, relax security settings,
or treat a local source launch as proof that an internet download is trusted.

## Owner-controlled preparation

The Apple account owner and repository maintainer must authorize and perform the
credential and account steps themselves, through official account interfaces.
Do not send credentials in issues, pull requests, chat, screenshots, logs, or
artifacts. Setting up persistent CI access and accepting account agreements are
separate decisions from approving a documentation change.

1. Confirm access to the intended Apple Developer team and any required account
   agreements. For the manually managed identity used here, Apple's
   [Developer ID certificate instructions](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/)
   specify the Account Holder role. Select **Developer ID Application**, which
   signs a Mac app; **Developer ID Installer** is for installer packages. This
   workflow builds an app ZIP, not a `.pkg` or Mac App Store submission.
2. On a trusted owner-controlled Mac, obtain the appropriate certificate and
   matching private key. In Xcode, open Settings > Accounts, select the account
   and team, and open Manage Certificates. Export the intended signing identity
   as a password-protected `.p12` using Export Certificate. A public `.cer` alone
   cannot sign; the private key must be present. Follow Apple's
   [identity export instructions](https://developer.apple.com/documentation/xcode/sharing-your-teams-signing-certificates).
   A cloud-managed signing service is not a drop-in replacement for this
   workflow's imported `.p12` identity.
3. Record the exact installed Developer ID Application identity name and team.
   The local read-only command `security find-identity -v -p codesigning` can
   help identify the intended identity; do not guess from a person's name.
   Encode the exported `.p12` as Base64 locally, outside the checkout, for
   `APPLE_CERTIFICATE_BASE64`. Base64 is an encoding, not encryption; handle the
   encoded copy as private-key material too.
4. Have the account owner generate a dedicated app-specific password through
   [Apple Account](https://account.apple.com/). Apple's
   [password instructions](https://support.apple.com/en-us/102654) require
   two-factor authentication. This is not the primary Apple Account password
   or the `.p12` password. Record the correct Developer Team ID from the
   [Apple Developer account](https://developer.apple.com/account/).
   Apple's [notarytool credential guidance](https://developer.apple.com/documentation/technotes/tn3147-migrating-to-the-latest-notarization-tool)
   describes the account/password/team combination used here.
5. Only after the owner approves that CI credential access, add the exact secret
   names below in repository Settings > Secrets and variables > Actions >
   Secrets > New repository secret. Use the intended repository, not ordinary
   variables or a committed `.env` file. See
   [GitHub's secret setup guide](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).
   This job has no `environment:` declaration: merely creating environment-only
   secrets or an environment approval policy does not wire them into this job.
   Organization secrets must explicitly allow this repository. Changes to
   environments, access controls, or workflow gating require separate review.

The workflow consumes six secrets:

| Actions secret | Exact use in the existing workflow |
| --- | --- |
| `APPLE_SIGNING_IDENTITY` | Identity passed to `codesign --sign`; choose the complete Developer ID Application identity belonging to the intended team. |
| `APPLE_CERTIFICATE_BASE64` | Base64-encoded exported `.p12`, decoded to a temporary file and imported into a temporary keychain. |
| `APPLE_CERTIFICATE_PASSWORD` | Password passed to `security import -P` to unlock that `.p12`; it is not the temporary keychain password. |
| `APPLE_NOTARY_APPLE_ID` | Apple Account identifier passed to `notarytool --apple-id` for the authorized team account. |
| `APPLE_NOTARY_PASSWORD` | That account's app-specific password, passed to `notarytool --password`. |
| `APPLE_TEAM_ID` | Developer team identifier passed to `notarytool --team-id`; use the intended signing/distribution team. |

All are optional for the unsigned path. The signed path checks **five** values
for nonemptiness: identity, encoded certificate, notary account, notary password,
and team ID. **The certificate password is consumed but not checked by that
condition.** An absent or incorrect password for a protected `.p12` therefore
causes import failure after the signed path is selected. It does not select the
unsigned fallback. A nonempty value also does not prove that any credential is
valid. API-key authentication and saved notary keychain profiles are not wired
into this workflow; do not substitute their values into these secret names.

The six values are job-level environment variables, including during dependency
installation and tests. Review the selected source, dependencies, and workflow
before granting access. Never enable shell tracing or print the values to debug
a failure. Account owners retain responsibility for credential storage, expiry,
rotation, revocation, and repository access.

## What the current workflow actually does

The `macOS Desktop Preview` workflow can run manually or on a pushed `v*` tag.
It uses `macos-latest`, Python 3.12, and the pinned PyInstaller/hook versions in
the file. It checks checkout freshness, runs desktop/script tests, builds
`dist/LearnNote.app`, and copies the documented resources into the bundle.
There is no explicit Intel/Apple Silicon build matrix or universal-binary step.

When the five-value condition is met, the signing step:

1. Decodes the `.p12` into `$RUNNER_TEMP/learnnote-signing.p12`.
2. Creates and unlocks `$RUNNER_TEMP/learnnote.keychain-db`, using the
   `$RUNNER_TEMP` path string as its password; imports the identity and sets the
   key partition list for Apple signing tools. This is the workflow's existing
   behavior, not a recommended reusable keychain-password scheme.
3. Runs `codesign --force --deep --options runtime --timestamp --sign` on the app.
4. Creates `$RUNNER_TEMP/LearnNote-notary-submission.zip` from that signed app
   with `ditto`. This submission archive is outside the uploaded ZIP glob.
5. Submits that temporary ZIP with `xcrun notarytool submit ... --wait` using
   the account, app-specific password, and team ID.
6. Staples the ticket to `dist/LearnNote.app`, then runs `xcrun stapler validate`
   and `codesign --verify --deep --strict --verbose=2` on that app.
7. Creates the final `LearnNote-macOS.zip` from the stapled app. Extracts that
   final archive into a fresh temporary directory, then validates the extracted
   app's ticket and signature with the same commands. Failure stops the job
   before the artifact/release upload.
8. Removes the temporary `.p12` only if execution reaches the final command.

If any of the five gate values is absent, it instead creates
`LearnNote-macOS-unsigned.zip`. A failure in the signed step fails the job; there
is no signing-error recovery to the unsigned branch. On success, the artifact
upload retains the matching ZIP and `build/macos/freshness.json` for 14 days.

The job requests `contents: write`. For a `refs/tags/v...` ref with the five
values present, its final command is `gh release upload ... --clobber` for
`LearnNote-macOS.zip`. This expects an existing release, can replace an asset of
the same name, and does not create or enforce a draft-only review transaction.
The condition is based on the ref, not the event type: a manual dispatch on a
matching tag can reach publication too. A manual branch run does not reach that
upload but **still signs and submits the software to Apple** when configured.
Do not dispatch this release workflow as a supposedly credential-free test.

## Known limitations before distribution

- **The corrected ZIP path still requires a real signed run.** Previously,
  the distribution ZIP was created before stapling and never recreated. The
  corrected workflow packages after stapling and verifies an extracted copy;
  source review and static contract tests do not establish that those Apple
  commands have succeeded with a real identity. Apple's
  [custom notarization guidance](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)
  calls for repackaging the stapled contents because ZIP files cannot themselves
  carry a stapled ticket. An online notarization ticket alone is not evidence
  of offline first-launch acceptance for the delivered archive.
- `notarytool --wait` waits for a result, but the workflow does not retrieve and
  retain the detailed notary log or independently check a parsed `Accepted`
  status. Preserve the submission ID and review the result and warnings before
  making any acceptance claim. Extracted-app ticket/signature checks do not
  replace Gatekeeper assessment or a clean-machine download/launch test; those
  are not performed by this workflow. Apple recommends checking the notary log
  even for successful submissions
  in the same [customization guide](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow).
- The current recursive `--deep` signing command is not an audited inside-out
  signing plan for every nested executable. Apple recommends individual
  inside-out signing stages in
  [TN2206](https://developer.apple.com/library/archive/technotes/tn2206/).
  Hardened runtime and timestamp flags alone do not establish correct nested
  signatures, entitlements, or application behavior. Review the actual bundle
  and [notarization prerequisites](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
- The script has no explicit `codesign --keychain` argument or keychain
  search-list setup. Confirm the imported identity is actually discoverable in
  the runner before declaring setup complete. The `.p12` removal is not in an
  always-run cleanup step, and the temporary keychain is not explicitly deleted.
  Do not reuse these steps on a persistent/shared runner without a separate
  credential-lifecycle review; no such changes are made here.
- There is no final-asset checksum/download comparison in this macOS workflow.
  Do not assume the Windows release publisher's draft/verification safeguards
  apply to this direct upload command. Likewise, a passing build is not proof
  of macOS x64 coverage, a universal build, automatic update support, migration,
  or a production release.

## Evidence required for a future signed release

After a separately authorized signed run of the corrected workflow, retain the
source commit, run URL, runner architecture/OS, tool versions, notary submission
ID, accepted result, reviewed notary log, final ZIP digest, and extracted-app
verification results. Keep private credentials and account identifiers out of
public evidence. Notarization is an Apple security check, not App Store review
or application functional acceptance.

On a macOS verification machine, these commands inspect an app extracted from
the **final candidate ZIP**; substitute its actual path. They are not commands
to sign, submit, publish, or bypass a failed policy check:

```sh
codesign --display --verbose=4 "/path/to/extracted/LearnNote.app"
codesign --verify --deep --strict --verbose=2 "/path/to/extracted/LearnNote.app"
xcrun stapler validate "/path/to/extracted/LearnNote.app"
spctl --assess --type execute --verbose=4 "/path/to/extracted/LearnNote.app"
shasum -a 256 "/path/to/final/LearnNote-macOS.zip"
```

Confirm the expected Developer ID/team and inspect each result; file names and
successful CI status are insufficient. Apple's
[notarization troubleshooting guide](https://developer.apple.com/documentation/security/resolving-common-notarization-issues)
explains signature and policy checks. Also test the actual downloaded archive
under normal quarantine and Gatekeeper behavior on the claimed target systems,
including offline first launch where that is promised. A digest identifies the
tested bytes; it does not replace identity, notarization, or launch checks.

Leave signed-distribution status pending until the exact delivered artifact has
the required evidence. Preserve existing unsigned/source-build claims and their
limits independently.
