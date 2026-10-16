# Native macOS version upgrade and snapshot rollback gate

Status: harness and source-only rehearsal; native hosted acceptance is pending.

Run `Native macOS version rollback gate` manually with no inputs. It builds two
separate immutable source checkouts in separate Python environments:

- 0.2.14: `5a1db274f68df792149658ff2bb27894870eb608`, also checked against tag
  `v0.2.14`. Its macOS spec has `exclude_binaries=True` without `COLLECT`. The
  gate applies only the recorded `COLLECT`/`BUNDLE` packaging correction. This
  is a disclosed old-source rebuild, not an untouched historical release asset.
- 0.2.15: `ee32db1e1c78bbe46c7a5aaa444d4f990383c3d1`, unmodified source.

The build manifest retains Git and source-tree identities, original/used spec
hashes, the complete packaging patch, installed dependency versions, pinned
PyInstaller/hook versions and app-tree hashes. Dependency resolution is recorded;
these are not claimed to be bit-reproducible builds.

The native sequence uses a disposable data directory at one fixed absolute path:

1. Launch the old app, verify health version, wait for its loaded native window,
   and capture only that process's window. Import a Unicode Markdown material,
   add a personal annotation, and finish an actual caption-only task through the
   public API. The supplied captions are synthetic; no model or ASR is used.
2. Stop the app and copy its complete data tree to `pre-upgrade-snapshot`.
   Verify every retained file's bytes against its SHA-256 inventory.
3. Launch the new app on the same active data path. Verify task ID, exact caption
   timing/text, material bytes, Markdown/SRT exports and personal annotation.
   Add a new annotation and verify both annotations.
4. Stop the new app. Preserve its complete state in `upgraded-snapshot` and
   `upgraded-active-data`. Copy the untouched pre-upgrade snapshot back to the
   original active path, then launch the old app again and recheck original
   records and exports. Both immutable snapshots must still match their inventories.

Every native phase verifies its actual version and owned loaded-window identity.
PNG captures require manual inspection for visible application content. A loaded
window title and a successful screenshot command alone do not prove visual quality.
The gate fails rather than requesting accessibility or screen-capture permission.

All synthetic snapshots, inventories, logs, build provenance and screenshots are
retained in the workflow artifact, including hidden files under its owned output.
Failures preserve their primary error while attempting independent process cleanup.
No release/tag/assets, signing credentials, user data or security settings are changed.

## Acceptance boundary

A pass demonstrates manual rollback by restoring the **pre-upgrade data snapshot**
and starting the genuine older application build. It does not show that the old
binary can open newer-schema data, or that edits made after upgrade can be
converted to the older schema. Those edits remain available in the separate
upgraded snapshot. It also does not cover notarization, x64 macOS, provider/model
execution, ASR, real media sites, credentials or extension pairing.

The local rehearsal runs actual old/new source backends under an external-network
block and exercises the same API/snapshot sequence. It is useful compatibility
coverage, but it is not a native packaged-app or screenshot acceptance result.
