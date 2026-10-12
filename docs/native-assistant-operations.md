# Native assistant operations: first execution slice

The desk assistant's **操作软件** button opens real local tools for the selected
saved note. This is the first execution slice, not a complete autonomous agent.
It supports reading bounded lines, editing a personal revision, generating a
Markdown/HTML/Word/PDF file, and changing eight browser reading preferences.
Courses, task lifecycle and reusable templates are not yet in this tool vocabulary.
A separate [bounded note workflow](native-assistant-runs.md) can sequence reading,
a reviewed edit, verified readback and export. Existing source files and generated notes remain intact.

## Proposal and execution

The local forms require no model. The natural-language form makes one structured
model-tool decision using the selected connection. It does not use keyword routing
as execution authority and does not execute the returned call automatically.
Unknown tools, extra fields, multiple calls and incomplete responses fail closed.
A model cannot supply a different source ID, path, endpoint or credential.

Only the current request, fixed source identifier/revision and allowed reading
preferences are sent by default. Sharing the saved body requires a per-request
checkbox; over 24,000 characters is rejected explicitly. There is no implicit
history or extra session-log upload. No real provider call or key is required by
the test suite. This implementation adds no DeepSeek Harness runtime dependency.

Each proposed operation has a visible preview and a separate execution action.
An edit preview includes the exact diff. Replacement must match exactly one
literal occurrence; title editing finds a prose H1, ignoring fenced code.
An unsaved draft, changed selection or changed saved revision blocks execution.
The dialog reuses existing workspace styles and reading preference controls.

## Local journal and recovery

The API is under `/api/assistant/operations`. Planning is read-only; `prepare`
creates a record without changing a note. `/{id}/execute` requires `confirm:true`.
Stable IDs bind the source, revision, tool and validated arguments. Replays return
historical receipts without applying the operation again. A receipt is evidence
of what that operation did, not a claim that later user work has not changed it.

A process-wide lock and an OS-backed lease serialize executions and deletions.
Manual and assistant edition writes also share a version check and edition lease.
Each personal save atomically carries a write marker: a fresh ID for manual saves,
and the operation ID for assistant saves. Recovery and Undo compare this marker
as well as the body hash, so a later manual return to identical text is protected.
Older editions remain readable without migration; an interrupted old operation
without enough marker evidence becomes a conflict rather than being replayed.
The lock order is operation store, edition, then source storage/index. Deletion
acquires the operation lock before the source locks, including task-linked
material registrations. Windows uses the existing named-mutex lease implementation.

Preparation reserves terminal/recovery bytes and one undo record for an edit.
Serialized record sizes are checked before accepting a proposal. The store is
bounded to 64 reserved slots and 16 MiB of journal reservations; edit proposals
reserve two slots. Each serialized record is at most 3 MiB. Export artifacts are
bounded separately. Filling the quota cannot consume an accepted edit's undo
reservation. The user can delete terminal records to reclaim their local copies.

Cancellation is effective before the commit boundary. Once a note or artifact
is committed, a late cancellation reports the actual completed result. After an
interruption, exact before/after hashes and write markers reconcile the note; newer user content is
never rolled back speculatively. Disk failure after a commit returns a truthful
result with a persistence warning, retaining the prior record for reconciliation.
An interrupted undo-link write restores a usable Undo action.

Undo is one guarded inverse operation with its own stable ID and reserved record.
It succeeds only while the current revision and write marker match the original
result. A conflict preserves later work, including a later save of identical text.
This is not a stacked undo system: undoing a newer edit writes a new marker, so
an earlier operation does not regain Undo authority automatically. Undo receipts cannot themselves be undone by this
slice. Closing the dialog stops waiting on model planning, but does not claim to
roll back a backend operation; actual status remains available in the journal.

## Data lifecycle

Read receipts can include body text. Edit records include complete before/after
copies, and export operations retain their generated files. These are local data,
not harmless metadata. The UI and privacy notice disclose them. Forgetting a
terminal record removes its linked undo record and export copies without changing
the current note. The UI confirms that its recovery history will be lost.

Deleting a source removes its related assistant copies, including registered
material aliases of a deleted task. Lease-protected cleanup also removes only
strictly named abandoned atomic-write temporary files. Unknown user files are
preserved. If source metadata is missing or damaged, records are not served and
recovery copies are preserved; absence alone is never treated as permission to
destroy a backup. Explicitly confirmed record disposal can still remove a stranded
copy after its source was deleted, under the operation lease. Corrupt journal data
or failed cleanup returns an explicit error.

Reading settings use the existing browser preference JSON with atomic receipt
storage and Web Locks for cooperating tabs. See [reading-settings-api.md](reading-settings-api.md)
for supported values, conflict handling and limits of unrelated legacy writers.
The tool cannot change notification permissions, model connections or security settings.

## Verification

- `scripts/test-backend-offline.py` rejects external transports during backend tests.
- `backend/tests/test_assistant_operations.py` covers revisions, real document bytes,
  cancellation, quota and crash boundaries, corruption and source cleanup.
- `web/tests/assistant_operations.test.mjs` drives the real UI controller and the
  reading adapter with synthetic fixtures, including stale callbacks and failures.
- `scripts/assistant-operations-visual-acceptance.cjs` is the Windows Edge gate
  with the actual local backend. Only the model proposal response is mocked;
  execution, files, settings, undo and deletion are real synthetic operations.

Passing local unit/HTTP checks does not establish the Edge gate or a real selected
provider integration. Those must be reported separately for the exact commit.
