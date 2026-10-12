# Bounded provider-streamed topic drafts

This is one slice of issue #151, not a claim that general provider streaming or
semantic chapter quality is solved. It adds no dependencies, endpoints, probes,
credentials, planning requests, or verification requests.

## Explicit profile and unchanged paths

Only the exact selected base URL `https://api.openai.com/v1` (optionally one
trailing slash) with model `gpt-4.1` or `gpt-4.1-2025-04-14` uses the new profile.
It requires the existing partial-section callback and one to three existing
source blocks. The following paths keep their existing requests and output:

- Other models, snapshots, compatible/custom endpoints, proxies and Azure routes
- Vision requests, including their text fallback after failed vision batches
- More than three source blocks: existing recursive text requests and completed
  parent-bound `text_chunk` drafts; text-only children do not invent global times
- Calls without the partial-section callback, empty source and local fallback

The exact allowlist is deliberately narrower than all potentially capable
models. There is no capability probe or automatic endpoint/model switch.

Official references checked 2026-10-12:

- [GPT-4.1 model](https://developers.openai.com/api/docs/models/gpt-4.1): exact
  alias/snapshot, Chat Completions, streaming and structured-output support
- [Create Chat Completion](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create):
  strict JSON schema response format and stream options
- [Chat Completions streaming events](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events):
  content deltas, refusal, finish reasons and choice-less usage chunk

## Request and publication boundaries

The selected text-summary request now asks for a strict JSON envelope containing
complete topic chapters (`title`, `source_blocks`, `markdown`). Original source
blocks are labeled in place, not duplicated. Existing note style, template,
depth, question setting, page context, evidence instructions, selected model,
endpoint, credentials and provider request parameters remain in the request.
The already-selected source is transmitted to that same configured endpoint;
streaming does not make the source public or filter out private source content.
The SDK retains its configured pre-response retry policy. No consumer retry,
compatibility replay or nonstream fallback request follows a stream failure.
Tests count one explicit SDK completion call; that is not a claim of exactly one
wire attempt if the configured SDK retry policy handles a pre-response failure.

The parser is single-pass and bounded to 1 MiB total, 64 KiB per object, 32
chapters and 12,000 body characters per chapter. It decodes and emits only whole
chapter objects, rejects duplicate keys, extra fields, invalid Unicode and
foreign source indices, and requires a complete envelope, coverage of every
input block and an explicit successful `stop` finish before returning a note.
Only `delta.content` text is consumed. Reasoning is ignored; refusal/tool/audio output
fails closed. EOF, timeout, malformed tail and output-length termination leave
previously completed chapters as drafts and cannot publish a final note.

Provenance times and IDs come from original local source blocks. Literal times
and URLs from the selected source remain allowed in prose and code; newly
invented locators are rejected. Untimed source stays untimed. Source-block
selection is an unverified model attribution, not proof of
a claim. This protocol is more restrictive than free Markdown, so otherwise
useful responses that violate it may fail. No real model-quality experiment was
run for this change.

Completed `topic_chapter` sections reuse the durable partial writer, source and
attempt revisions, preserved previous artifacts, claim-review markers and
ready-event deduplication. A different generation in the same attempt cannot
replace active topic drafts. A source change or stale attempt cannot overwrite
them. Normalization and claim matching run before taking the global lock, so
other task reads and cancellation stay available during this expensive work.
Topic publication rechecks that prepared content is current and holds the same storage RLock as `start_pipeline_attempt`
across source/attempt validation, previous-section reads, JSON/Markdown/pointer
writes and ready-event publication. A deterministic two-thread barrier test
reproduced the old callback overwriting a newer attempt before this lock was
added, then verifies the new attempt's artifacts and events remain current.
This does not change the existing vision/text-chunk writer's locking policy.
The Markdown reader shows complete chapter headings, locally generated
source locators and the existing draft/evidence-pending warnings. Visible
provenance uses at most three coarse source-block ranges, while structured
provenance preserves every original cue window. The specialized
visual outline renderer deliberately falls back to this Markdown path, just as
for text chunks; this slice does not add a new frontend renderer.

The JSON is converted locally to Markdown before the existing final grounding
gate. Existing grounding repair calls still occur when required; “one request”
describes the selected summary request only, not a promise that repairs cost
nothing. Neither draft metadata nor model output can set `verified=true`.

The response stream is closed on success, error and cancellation without closing
the shared SDK client. A small cancellation watcher also closes an idle response,
but the real SDK loopback test found that cross-thread close does not reliably
interrupt a blocked read. Existing SDK IO timeouts and its pre-response retry
policy remain unchanged; no short read cap or new total-generation deadline is
introduced. No later chapters or final-gate work run after cancellation is
observed, but return from a currently blocked read can take up to the configured
IO timeout. Cancellation during initial request creation similarly waits for
the SDK's timeout/retry behavior. This does not guarantee immediate cancellation
of provider compute. Provider usage is recorded once after
consumption, and missing usage remains unknown rather than zero.

## Offline evidence

`backend/tests/test_streamed_chapters.py` labels its SDK-shaped mocks explicitly.
It also uses the real installed OpenAI SDK against a genuine loopback HTTP/SSE
server: the server withholds chapter two until chapter one's Markdown and ready
event have been persisted. Split wire bytes include multi-byte Unicode. This
fixture does not expand the production profile or contact a model provider.

Focused tests run under `scripts/test-backend-offline.py`'s unchanged external
transport guard. They cover framing/escaping/limits, source binding, durable
early visibility, final gating, cancellation/timeout, cleanup and usage, replay,
attempt/generation/source mismatch, previous artifact preservation and unchanged
nonstream requests. These are protocol and local integration tests, not evidence
of live provider quality or long-duration client performance.
