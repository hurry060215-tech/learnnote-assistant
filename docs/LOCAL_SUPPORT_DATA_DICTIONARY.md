# Local activation and support summary

Issue #145. Default network transport: **none**. The existing local HTTP API is
used by the workspace; there is no remote support sender, analytics endpoint,
background upload, tracking pixel or device identifier.

## Data dictionary

Only these fields can be previewed or exported:

| Field | Meaning | Value |
| --- | --- | --- |
| installed | Local backend has started | boolean |
| desktop_connected | Extension reached the local heartbeat endpoint | boolean |
| first_task_started | A task entered running state | boolean |
| first_task_succeeded | A task entered success state | boolean |
| error_categories | Coarse failure categories | connection/download/transcript/model/storage/content/other |
| version | Installed application version | release version |

The SQLite store contains only bounded fact names and expiry timestamps. No
task IDs, URLs, titles, transcript, screenshots, cookies, keys, account IDs,
machine identifiers, IPs or user-agent strings are recorded. Exact timestamps
are never exported. Facts expire after 30 days; expiration runs on each access.
Version is read from application code, not the device. Milestones describe
the retained local observation window, not a global installation count.

## User controls and privacy review

Settings → Storage and diagnostics exposes the checklist, recording switch,
delete-and-disable control, field selection and exact JSON preview. Closing
the panel or cancelling does not send or export anything. Saving requires
checking the review box; changing fields clears that approval. The downloaded
file contains exactly the visible preview. Sharing is a separate manual step.
The support link opens GitHub without a prefilled payload or tracking query.

Disabling preserves existing facts until expiry; deleting clears facts and
disables subsequent recording, including after restart. Explicit re-enabling
starts a new local observation window. Failed diagnostics never block task
processing. SQLite secure deletion overwrites removed row content; this is
not a claim of forensic erasure of filesystem or user-created backups.

Privacy review: six-field allowlist; coarse error mapping before persistence;
concurrent idempotent writes; 30-day expiry; disabled-state persistence;
preview/export equality; no sender route; DOM text-only rendering. Tests cover
private-looking error inputs, unknown fields, disk errors and cancellation.

## Store metrics review playbook

Use only the authenticated store dashboard's aggregate installs, active users,
uninstalls and reported connection/support failures. Record the period and
store version, compare aggregates with release dates, and label sampling
limitations. Do not join dashboard information to local summaries or attempt
cross-device/cross-site identification. Store access or publishing a new
disclosure is a separate authorized account action; this code does not do it.

Public-site UTM values, if used in a manually prepared campaign link, identify
only that public landing-page source. Do not copy them into the extension,
task records, support payload, cookies or a cross-site identity. This feature
adds no UTM collector. Current store copy must say diagnostics are local and
user-exported, never that LearnNote receives automatic activation telemetry.
