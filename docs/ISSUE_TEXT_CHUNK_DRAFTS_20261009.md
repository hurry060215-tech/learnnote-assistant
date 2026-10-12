# Existing long-text requests as readable drafts (#151 / #148 increment)

When the existing text summarizer splits a source into more than three blocks,
each successful child request now publishes a readable draft before the parent
dispatches the next request. Short sources still use one request. The block
partition, prompt text, provider compatibility retry, grounding repair and
final assembled text are unchanged. This adds no provider calls or transmission.

These are source chunks, not semantic chapters. Their headings are stable,
unique labels such as `文字分段 1`. The subtitle-first, saved-transcript retry and
existing media paths pass the same callback. The extension sidepanel does not
receive a new progressive reader in this increment.

## Additive local projection

`partial_note.json` remains schema version 1. A `text_chunk` section has its
original zero-based `block_index`, SHA-256 `block_digest`, and `source_windows`.
Its identity includes the existing source revision (original transcript and
media hash), index and digest. Repeated identical blocks remain distinct.
`generation_revision` hashes the model, endpoint, source blocks, title, context,
non-secret options and prompt contracts. API keys are excluded.

Cue indices and exact bounds come only from the original transcript. A cue
split across requests keeps its original bounds; it does not acquire invented
sub-cue timing. Untimed sources use empty windows and omit `start` / `end`, even
when generated prose contains a timestamp. Incoming and saved text identities
are checked against the original block builder.

Every section has `status=evidence_pending` and `verified=false`; the document
is also an unverified draft. Local claim-review markers remain visible, and the
reader labels say `草稿` and `待最终来源检查`. A valid citation, successful request
or final successful task does not establish factual verification. No semantic
verification call or verified badge is added.

## Preservation and recovery

The shared writer retains attempt guards, generation/source revision separation,
durable JSON and Markdown before ready events, replay deduplication and unchanged
reader revisions. Existing source bytes, `draft.md` and previously published
notes are preserved. Failed or cancelled later work keeps completed drafts;
drafts stay excluded from generated-note retrieval and task QA. Final publication
still passes through its existing quality and claim checks.

There is no new text cache or chunk resume protocol. An interrupted Markdown
projection can be repaired when the same completed payload is delivered again;
an ordinary text retry still makes its existing requests. Unknown future schemas
are preserved. Rollback can point the reader at retained `draft.md` without
deleting the additive projection or changing original evidence.

## Validation and boundaries

Synthetic fake-SDK tests compare the 72,000-character case with callbacks on/off:
five identical requests and identical final text, with a readable chunk before
each subsequent request. They cover split-cue partition parity, timed/untimed
identity, compatibility retry, cancellation, stale attempts, changed source and
generation, CRLF replay, failed drafts, retrieval exclusion, both text wrappers,
final quality rejection and final-success verification boundaries.

The existing Edge fixture now runs vision and text scenarios against shipped
reader assets, including duplicate events, repeated subheadings, reading position,
selection, hostile text, failed/retried drafts and explicit final success. Its
self-test does not launch a browser. Real Edge rendering is a separate Windows
CI check; no browser or live model evidence is claimed by the local self-test.

New pure source identity code and the existing block/persistence modules receive
small explicit line limits without expanding existing architecture budgets.
True per-section semantic verification, semantic chapter discovery and sidepanel
progressive delivery remain open issue criteria.
