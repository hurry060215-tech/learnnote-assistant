# Short non-stream response drafts

This bounded addition covers issue #151's short text response path. A source of
one to three existing text blocks can show the one provider response as a
pending draft before the existing final validation finishes. It does not add a
request, change the prompt or provider options, delay final publication, split
the response into invented chapters, or guarantee earlier provider output.

Only an explicit provider `finish_reason="stop"` is eligible. Missing, unknown,
length-limited, filtered or tool-call completion metadata produces no complete
response draft. The original final validation still handles the response as
before. Quota errors produce no completed response draft.

The draft binds all actual input blocks, their digests and original source
windows, plus the source revision, pipeline attempt and generation fingerprint.
These windows locate the request's source range; they do not establish that
every generated sentence is supported. Original source files are preserved.
The draft remains `evidence_pending` with `verified=false`, including after a
failed final gate. Final success is not a factual-verification claim.

Draft projection errors are additive failures: an unavailable draft does not
discard the completed response or skip its final gate. Diagnostics record the
exception type without source content or local paths. Cancellation remains a
separate outcome and stops the subsequent gate. Stale source/attempt and replay
checks reuse the existing durable projection protections.

The existing official streamed profile, long-source parent chunks, actual
vision batches and their later text fallback keep their previous paths. No
live provider or paid model was used for these regressions.

## Verification

Synthetic provider responses exercise the real summarizer, final gate,
filesystem projection, source bindings, request counters, retries and failure
paths under the repository offline network guard. The new `response` scenario
in `scripts/progressive-sections-acceptance.cjs` checks the shipped reader with
one draft through progress, failure, retry and final success. Its API/events are
explicit fixtures; an actual browser run is required before UI acceptance.

Independent review found and corrected optional-write error propagation and
unconfirmed completion metadata. Full applicable suites and exact-head CI are
recorded in the pull request; this document alone does not claim they passed.
