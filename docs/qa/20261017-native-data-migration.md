# Native data-directory migration evidence (#70)

Status: the bounded unsigned macOS arm64 Quit/copy/restart acceptance passed;
reports, preserved state, exports and the restarted native window were inspected.

[Run 38993618885](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38993618885)
used exact commit `ba068363ef9057b81e165657338a8741226941e4`, macOS 26.6.2
arm64 and application version 0.2.15. Linux's separate source-backend lane also
passed; it is not a packaged Linux desktop test.

## Observed native sequence

- The unchanged frozen executable was copied into a disposable app bundle. Both
  launches used that executable without checkout `PYTHONPATH`, synthetic data
  and isolated homes; no signing secrets or release assets were involved.
- With original PID 15825 alive, helper PID 16088 stayed scheduled for 3.06 seconds:
  no staging, destination content or active-config change occurred.
- The existing native application Quit request returned success and exit code 0.
  The existing Python shutdown message appeared, the source session marker was
  removed and the old backend stopped. Forced cleanup was not accepted as Quit.
- The frozen helper copied the stopped source, checked ownership/schema/integrity,
  mapped one catalog material path in the destination and committed config last.
  The completed receipt and exact previous config were retained. The unrelated
  Unicode configuration value was preserved.
- The destination session selected `127.0.0.1:49263` rather than requested port
  49262, within the launcher's normal fallback range. Its URL selected routing;
  the known live helper, same version, exact destination health root and native
  window owned by PID 16088 established the restart. The inherited source data
  environment did not override the committed destination configuration.
- Real API reads before and after returned byte-identical original Markdown,
  content, annotation records and personal-backup exports. All nine source-file
  records, including SHA-256, size, nanosecond mtime, device/inode, and the source
  directory lists matched before shutdown, after shutdown and after migration.
- Catalog integrity was `ok` before/after; non-path row values/counts matched.
  The other three databases present in this fixture retained their schemas/rows.
  The source, destination and previous configuration remain in the artifact.

The restarted migration window visibly renders the home workspace and imported
`native` material. Window metadata/image hashes match. Baseline restart/restore
screenshots captured the readable initial landing view before full home hydration;
their content/backup assertions came from the actual API, not those screenshots.

## Reproduction and retained artifacts

Run `native-platform-acceptance.yml` manually. The macOS command is:

```sh
python scripts/native-platform-acceptance.py --app dist/LearnNote.app --migration-smoke --output build/native-acceptance
```

- [Native report, exports and windows](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38993618885/artifacts/12086271778), ZIP SHA-256
  `c2e270d6b4beae2ebf40ad2dbd72908c34ef36f788cf3337b208356f46fc766e`.
- [Synthetic source/destination/config/receipts, including hidden state](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38993618885/artifacts/12086545917), ZIP SHA-256
  `1168c667bb34cba8d01d9be19c882b114b3aba1a221551b0624eda64d770c73e`.
- [Linux source-backend report](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38993618885/artifacts/12086535683), ZIP SHA-256
  `ca87b4e78e1cd96433cd327552c73ef05a2d98867d9b64bae4335b116ce423d0`.

The artifacts have 14-day retention. Failure uploads use the same narrowly
scoped synthetic paths, including incomplete hidden stages; they exclude app
bundles and isolated home/cache directories.

## Boundaries and negative evidence

Earlier [run 38991753249](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38991753249)
failed because upstream Cocoa application Quit bypassed Python cleanup. The
reviewed lifecycle adapter routes approved Quit through the existing window-close
path and preserves veto/confirmation. [Run 38992782052](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/38992782052)
then proved Quit/copy/config activation but failed because the harness polled the
requested port instead of the destination's selected port. Neither failure was
reported as passing, and the final strict cleanup/export/snapshot gates remain.

Automated contracts separately cover cancellation, nonempty/conflicting targets,
changed snapshots, links, unsupported schemas, rollback journals, interruption
before/after config commit, receipt failure and post-activation launch failure.
See [the migration guide](../DATA_DIRECTORY_MIGRATION.md) for recovery steps.
The separate [task portability report](20261016-task-path-portability.md) covers
cross-platform copied-task readers; [version rollback](../QA_NATIVE_VERSION_ROLLBACK.md)
restores a pre-upgrade snapshot instead of downgrading newer data.

This run does not exercise native window Close, the actual native settings bridge
or folder dialog, signing/notarization, macOS x64, Linux native packaging, NAS
runtime performance, credential transfer, macOS extension pairing, remote models
or real media sites. It does not infer arbitrary foreign-root mappings or convert
newer database schemas to old versions. These limits remain explicit in the
[support matrix](../PLATFORM_SUPPORT.md).
