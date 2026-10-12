# Task and course controls

Open **Operate software**, choose **one existing task** or **one existing
course**, then select the exact item. Reading a target refreshes its revision.
The local forms require no model. A natural-language request uses the selected
text model to propose one typed tool; inspect the preview before executing it.
Source content and bounded status details are shared only with the explicit
per-request checkbox. A model cannot choose another target or execute a command.

## Task cancellation

Cancellation applies to one logical processing generation. Routine progress and
media enrichment retain that generation; a retry gets a new one. A stale preview
cannot cancel a replacement generation. Files already produced remain intact.
Pending browser handoffs still use the ordinary task panel's cancellation path.

The receipt distinguishes an accepted request, prevented queue dispatch, worker
acknowledgement, and confirmed callback completion. A request does not prove the
worker stopped. Missing queue evidence remains unknown. Restart recovery can
prove the previous worker is no longer active without pretending that its
callback completed normally. Cancellation has no undo.

Refresh actual status to read a new observation. The persisted historical
request remains associated with its original generation. Retrying the same
operation ID never cancels a newer generation.

## Course pause and resume

Pause blocks future episode preparation. Existing tasks and already prepared
handoffs retain their identity. Resume permits future preparation and starts no
download, transcription or model call. A title, membership or revision change
invalidates an older preview. To reverse the setting, refresh and explicitly
apply its opposite value; existing source files are preserved.

## Recovery and local records

The operation journal retains bounded status snapshots and control receipts.
The latest control marker remains in the task/course manifest for crash
reconciliation. Deleting an operation record does not reverse the control.
Deleting its source removes linked assistant records using the existing cleanup
guards. Missing/corrupt metadata prevents replay and leaves recovery data intact.

The queue schema update is additive. Existing persistent queue databases receive
an integrity-checked SQLite backup before migration, including committed WAL
pages. Backup/schema failures leave the original database intact. Backup files
contain task identifiers and queue state; keep them with the local data backup.
Any manual restoration must happen with the backend stopped and must account
for tasks created after the backup. Do not overwrite a live database.

The bounded multi-step note workflow remains focused on read/edit/readback/export;
task/course controls are reviewed single operations. There is no shell, source-code
editing, installation change, new credential, or background collection tool.
