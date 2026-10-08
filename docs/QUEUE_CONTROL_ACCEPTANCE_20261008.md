# Durable pause and priority controls

Refs #132. This completes the previously documented local queue-control gap.
The prior queue admission/download-stage repair and real ASR evidence remain
in [the budget report](QUEUE_BUDGET_VERIFICATION_20261008.md).

- A local SQLite migration adds bounded priority0–5 and persistent pause state,
  retaining existing jobs, sequence, context requirements and checkpoints.
- Pause prevents new claims atomically; already running work continues. Resume
  releases queued intents. Cancellation stays available while paused.
- Pending tasks can choose normal/priority in the desk. Already admitted tasks
  cannot mutate their priority. Queue position reflects effective priority.
- FIFO is preserved within equal priority. Every60 seconds waiting adds one
  effective priority level, so new priority work cannot indefinitely starve
  older normal work. These controls do not add remote scheduling or telemetry.
- The desk explicitly explains that pause does not interrupt running work.
  Existing per-task Stop preserves available checkpoints for explicit resume.

Deterministic acceptance tests cover old-journal migration, pause read by a
second queue instance,5 queued intents with cancellation while paused,
uninterrupted active work, selecting a later owned job without deadlock,
FIFO/priority position, waiting-time fairness, and strict API payloads.
Actual JavaScript DOM tests exercise pause/resume/priority paths and the lack
of a priority editor for running/completed tasks. All existing admission,
cross-process lease and recovery tests must remain passing.

Priority and pause are stored only in the selected local data directory.
Disabling the app does not erase pending intents. Browser login/model context
is never serialized; restart still requires the established explicit re-handoff
for tasks that depended on ephemeral credentials. Per-lane budgets retain the
documented default of one heavy task and independent configurable light and
download slots. Low-resource mode clamps budgets without dropping tasks.
