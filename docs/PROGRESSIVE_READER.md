# Reading while visual notes are generated

In the default reader, a visual task can first show its saved subtitle excerpts
grouped by their original time ranges. When a completed visual batch becomes
available, its draft is added beside the first subtitle section overlapping one
of that batch's actual source windows. Existing subtitle passages and unchanged
visual batches retain their DOM nodes, selection and reading position.

These are temporal groups, not inferred topics. A batch covering several groups
is labelled as crossing sections and is displayed once. A batch with no matching
subtitle group stays in a separate unmatched area. Gaps between sparse source
windows do not count as matches. Every generated batch remains an unverified
draft, with controls to open its source times. Exact-range frame grids belonging
to the selected task can be expanded for manual review.

This view uses the existing local, attempt-owned partial-note projection. A new
attempt or changed transcript starts a new view. A generation change discards
previous generated batches while retaining unchanged source excerpts. Late
responses from an earlier selection or read cannot replace the current view.

The saved Markdown remains the source for editing and export. User-edited
editions, final notes, text-only tasks and unavailable/invalid projections use
the regular reader. This feature adds no model call, external destination,
permission, storage migration or write to task artifacts.

## Validation boundary

Node regressions cover range matching, sparse windows, duplicate/invalid
projections, stable nodes, replay, attempt/generation changes, owned images,
stale asynchronous replies, editing and fallback. The existing Windows Edge
acceptance script also exercises the shipped reader with synthetic task APIs
and stream events, including source selection during visual arrival, source
image controls and the explicit transition to a final edition.

Those UI fixtures do not establish model quality, native WebView behavior,
low-end device performance or the full acceptance of issues #148 and #151.
Semantic chapter inference and per-section factual verification remain separate
requirements.
