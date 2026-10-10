# Bounded note workflows

The operation dialog's **连续读取、修改并导出…** entry adds a small execution loop
for one explicitly selected, saved note or material. The model chooses typed tools
from actual tool results. The loop can read, propose at most one personal revision,
pause for the user to apply its exact diff, verify the saved result by reading it
back, and generate a real Markdown, HTML, Word or PDF file. Reading followed by
export without an edit is also supported. It cannot manipulate arbitrary files,
run commands, change application source, select another source, configure a model,
or perform course/task lifecycle operations.

This builds on [single operations](native-assistant-operations.md). It is a bounded
note workflow, not a completed general-purpose agent or a DeepSeek Harness embedding.
The local operation forms and reading preferences remain available without a model.

## Scope and model data

Starting a workflow requires a fresh, unchecked sharing option. It authorizes this
workflow's current requirement, fixed source identifier/revision and actual read
results to be sent to the selected text model. The saved source must be at most
24,000 characters; a proposed edit exceeding that limit stops explicitly. Each
model request includes at most 24,000 characters of current-revision read results.
Subsequent decisions may resend these results. Older-revision read text is omitted
after the mandatory readback. This limit is not an estimate of total provider
input tokens or cost. The selected provider may charge for each request.

No prior chat, unrelated note, edit backup, arbitrary endpoint or extra session-log
upload is included. Model connection options and keys are not persisted in the run
record. The initial normalized endpoint/model fingerprint is fixed; selecting a
different connection stops the workflow. Normal explicit model connection rules
still apply. Test providers use only synthetic loopback responses.

## Execution and stopping

- At most eight model decisions, one edit, nine operation steps including readback,
  3,000 output tokens per decision, and 30 seconds for each provider request.
- The accumulated active-work budget is 120 seconds. Waiting for the user to review
  a diff does not consume that budget. A noninterruptible local operation may finish
  after cancellation or the deadline; its actual partial outcome is retained.
- Only explicit `advance` requests start decisions. The UI advances read/export
  steps and pauses at `awaiting_approval`. Reopening or refreshing a record alone
  never resumes model requests.
- A write requires `approve` with the current run version, exact pending operation
  ID and `confirm:true`. It uses the existing operation ID and atomic edition write
  marker. Exact before/after text and hashes are verified after saving. A model's
  claimed success cannot replace this readback.
- Successful completion requires an existing export whose recorded digest matches
  its real bytes. Incomplete/multiple/unknown tool calls, extra arguments, conflicts,
  missing receipts, elapsed budgets and prose-only completion claims stop the chain.
- Cancellation interrupts an async provider call and stops dependent steps. If a
  local write is already committed, cancellation preserves and reports that write;
  it does not claim rollback. The same guarded single-operation Undo remains in
  the operation history. There is no stacked or whole-workflow rollback promise.

The frontend also stops after a response is lost, a source or draft changes, the
view closes, or a server repeats the same ready version. It refreshes uncertain
receipts and retains a stable creation ID rather than automatically issuing a new
model request. The user must explicitly continue after reconciling an uncertain
response. It never replaces a newly created draft to refresh an older operation.

## Journals and recovery

This initial loop supports one backend service process. A status read from another
process treats a foreign in-flight attempt as interrupted and stops it; its late
response cannot execute another step. It does not pretend to distinguish a live
foreign worker from a restarted service. Disk operations still use the existing
cross-process leases. Multi-worker provider scheduling is outside this slice.

`assistant-runs` stores up to 16 small records, each at most 32 KiB. These contain
the user's requirement, fixed source and model fingerprint, state, limits and
references to operation records. The requirement may itself contain private text.
Read results, edit before/after backups and generated files are retained by the
existing operation journal and are disclosed in both dialogs.

A model attempt and its operation identity are persisted before execution.
A stale version returns the current record without starting a duplicate decision.
An interrupted provider attempt stops and is never automatically resent. A local
operation interrupted after committing is reconciled from its existing receipt,
artifact and write marker; later user saves are protected even if the text was
manually returned to the same content.

Deleting the source also removes its workflow requirements and references under
the shared journal lease. The separately confirmed “delete workflow record” action
removes only the goal and step index. It leaves the current note and operation
backups intact; those copies can be explicitly removed from operation history.
Unreadable records are preserved and reported as unavailable.

## API

The namespace is `/api/assistant/runs`:

- `POST /`: stable `run_id`, `question`, `source`, `share_source:true`, current `options`.
- `GET /` and `GET /{id}`: actual status and bounded step receipts.
- `POST /{id}/advance`: `expected_version` and current model `options`.
- `POST /{id}/approve`: `expected_version`, exact `operation_id`, `confirm:true`.
- `POST /{id}/cancel`: `expected_version`; a stale cursor still cancels live work.
- `DELETE /{id}`: `confirm:true`, for a terminal workflow record.

Responses include a monotonic version, source, actual steps, pending diff, verified
edit/export IDs, terminal reason and explicit limits. A status of `executing` with
`cancel_requested` means the service is still obtaining a local commit receipt.
Refresh it before claiming the note was unchanged. Pending cancellation/deadline
responses contain only control state, with no goal, source body or hydrated results.
Hydrated receipts validate source availability under the deletion lease, including
when cleanup failed after source removal.

## Verification boundary

Backend regression tests use the offline network guard and explicitly mocked model
responses. A separate synthetic loopback acceptance uses the actual async OpenAI
client, real HTTP routes, local journals and disk exports; the local provider's
responses are deterministic fixtures. These checks establish execution safety and
integration behavior, not the quality of an untested real model's decisions.

The workflow frontend has controller and synthetic DOM interaction tests. Use
`scripts/assistant-runs-visual-acceptance.cjs` for the separate actual Edge gate:
it drives the real UI and isolated backend against a deterministic loopback model
stub, including cancellation, lost-response recovery and a narrow viewport. Its
results must be checked for the exact commit. Native WebView and real-provider
validation remain separate; local unit/HTTP passes do not establish either one.
