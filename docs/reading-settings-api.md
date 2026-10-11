# Local reading-settings adapter

`window.LearnNoteReadingSettings` is installed by `installSettings` in the desk
client. It never calls the backend, notification permissions, model providers,
network configuration, or desktop/security APIs. It is available after settings
initialization. Only a successfully returned local receipt establishes that an
assistant action actually changed this browser/client's settings.

## Contract

- `read()` returns `{ok: true, settings, revision}` synchronously.
- `patch({operationId, expectedRevision, patch, signal?})` returns a Promise.
- `undo({operationId, targetOperationId, expectedRevision, signal?})` returns a Promise.
- `operation(operationId)` synchronously recovers a stored receipt, with current
  settings and revision. Missing/expired IDs return `operation_unknown`.
- `recentOperations()` synchronously returns `{ok: true, operations: [receipt]}`,
  oldest first. Read methods never write or migrate anything.

Use a stable unique operation ID (1–128 characters from letters, digits, `_`,
`.`, `:`, `-`) for every confirmed patch or undo. Reuse that ID and exactly the
same expected revision and payload when retrying. Property order does not matter.
An ID with a changed payload or revision fails with `operation_conflict`.
`signal` is an optional AbortSignal; cancellation is honored until the synchronous
storage commit begins. Once committed, cancellation cannot pretend it was undone.

A successful mutation returns:

```js
{
  ok: true,
  operationId: "stable-card-id",
  status: "applied", // "undone" for undo
  before: { theme: "light", size: 17, /* remaining six fields */ },
  after: { theme: "dark", size: 20, /* remaining six fields */ },
  revision: "opaque-current-revision"
  // targetOperationId is also present for undo
}
```

`settings`, `before`, `after` and `current` contain exactly the eight allowed
fields. Replayed operations and `operation(id)` add `replayed: true`, `current`
and `currentRevision`. Their original `after`/`revision` describe the historical
operation, which may no longer be the current appearance. Replays never write
again; they refresh the actual current appearance when no manual edits are open.
Do not display a replay's historical `after` as the user's current settings.

Failure returns `{ok: false, status: "failed" | "cancelled", error: {code,
message}}`. Check `ok`; never claim success based only on a backend plan, click,
or network response. `apply_failed` or `commit_unverified` also includes
`persisted: true`: the write succeeded but rendering or verification did not.
Re-read/recover/retry the same operation rather than issuing a new operation ID.
`commit_conflict` means a direct, noncooperating storage writer replaced the write;
read again. No rollback overwrites the other writer.

## Exact values

| Field | Allowed values / type |
| --- | --- |
| theme | `"light"`, `"dark"` |
| size | numbers `15`, `16`, `17`, `18`, `20` |
| font | `"sans"`, `"serif"`, `"mono"` |
| width | strings `"760"`, `"940"`, `"1120"` |
| leading | strings `"1.65"`, `"1.85"`, `"2.1"` |
| weight | strings `"400"`, `"500"`, `"600"` |
| density | `"comfortable"`, `"compact"` |
| accent | `"neutral"`, `"teal"`, `"blue"`, `"plum"` |

Empty patches, unknown keys and type coercions fail. `autoOpen` and `notify`
remain accessible only through the existing manual form; the assistant cannot
read them through this public boundary or change them. Other JSON members are
preserved unchanged. Receipts contain only allowed appearance fields.

## Persistence, races and undo

The existing `learnnote.reading.preferences` JSON remains the storage record.
The optional `theme` and `__learnnoteReading` metadata are added only by a save;
there is no startup migration. Without a saved `theme`, the existing
`learnnote.desk.theme` key remains the fallback. Theme, preferences and receipt
are committed with one atomic `localStorage.setItem`; a quota/permission failure
leaves the previous record and applied appearance intact.

Every save produces a new revision. The opaque revision also includes normalized
current values, so a legacy/direct writer retaining old metadata still
invalidates plans for changed settings. Always read before creating a new plan.
The last 64 successful assistant receipts are retained, pinning the most recent
patch for undo/reload recovery. A replay whose receipt has expired fails with its
stale original revision instead of reapplying. Failed/cancelled attempts have no
stored receipt. New IDs must be globally unique per card/action.

Agent writes require the same-origin Web Locks API; its absence returns
`locking_unavailable`. All current manual writes use the same lock when
available, and remain usable without it (without a cross-tab serialization
guarantee). Storage events refresh saved state in other tabs. Unsaved manual
appearance previews are retained with their old base revision; saving such a
stale preview fails until the user reviews/discards it. Any unsaved settings in
the active desk block agent writes with `unsaved_settings`.

Undo looks up the original successful patch, checks the expected current revision,
and requires all eight current fields to still match that patch's `after`.
Otherwise it fails without overwriting subsequent user changes. Manual-only and
unrecognized fields survive undo. Undo has its own ID and receipt.

Web Locks serialize this version's cooperating clients. localStorage has no
compare-and-swap primitive: unrelated legacy scripts that ignore the lock are
checked before/after the write, but cannot receive a stronger atomic guarantee.

## Internal manual boundary

`createReadingSettingsAdapter` in `web/reading-settings.js` accepts injectable
storage, locks, event target, document, preview element and dirty callback for
synthetic tests. The form uses `normalizeReading`, `applyReadingAppearance` and
`saveManual({preferences, expectedRevision})`; the latter additionally accepts
the two pre-existing manual task booleans. It is deliberately omitted from
`window.LearnNoteReadingSettings`. The form still owns notification permission
requests and live previews; all persisted appearance changes share the adapter.
