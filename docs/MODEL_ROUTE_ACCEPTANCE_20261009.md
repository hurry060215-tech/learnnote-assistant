# Model routes and offline readiness acceptance

Scope: [#146](https://github.com/hurry060215-tech/learnnote-assistant/issues/146)
and the concrete planning/disclosure bug
[#265](https://github.com/hurry060215-tech/learnnote-assistant/issues/265).
The separate audio credential-scope correction is tracked by
[#267](https://github.com/hurry060215-tech/learnnote-assistant/issues/267).
Integration baseline: the request-scope correction and architecture boundaries on main.
The final PR records its exact tested commit and tree.

## Original acceptance matrix

| Original criterion | Existing evidence | This change and remaining limits |
| --- | --- | --- |
| Distinguish text / vision / ASR / context / image limits | Route API already separates subtitle, ASR, text and vision execution paths; image verification is endpoint/model scoped and expires. | Versioned capability report distinguishes configured text, declared/tested/unknown/unsupported vision, local ASR files versus unverified remote ASR, and explicitly unknown context/image limits. Configuration is not an inference-quality test. |
| Show outgoing data before a task starts | Settings already lists audio, transcript, instructions and selected frames. Batch import already snapshots the displayed options and route. | The create dialog now shares that batch disclosure for text, visual and subtitle modes. Remote ASR is no longer described as local. Only parsed host identity is shown; URL userinfo, path, query and fragment are absent. Batch retries retain the original options/route. |
| Give a useful no-Key local route | Cached verified subtitles can be saved without a model; missing subtitles do not silently start ASR. Local ASR status checks cached files without downloads. | No-Key matrix proves route inspection across all content modes/local and remote ASR never constructs a provider client or prepares a model. Selected missing-Key connections no longer borrow readiness from an unrelated environment key. |
| Fall back on unsupported images / parameters | Existing deterministic image-rejection fixture falls back to a text completion; partial visual failures retain successful batches. | A structured 400/422 `unsupported_parameter` rejection naming `temperature` retries once without that optional sampling parameter. Successful recovery publishes actual AI text. Generic failures and failed retry preserve the original transcript/checkpoint for recovery. Other optional fields are not silently removed. |
| Label estimate ranges and uncertainty | Cost, duration, context and image limits are already unknown in the planner. | Settings and pre-submit disclosure show unknown cost/time ranges with the missing-evidence reason. No measured range, price, numeric limit, free-cost claim or timing guarantee is invented. |
| Provider updates do not change the core task schema | Provider presets and compatibility helpers are separate from `TaskOptions`. | Capability schema/catalog revisions are independent of the unchanged task and route schemas. A synthetic revision-update test proves that boundary. No new providers or adapters. |

The ASR disclosure names the same sanitized service host used by the selected
execution route. Configured text support does not imply configured audio
support. Planning and execution share the same scope validation. The separate
[#268](https://github.com/hurry060215-tech/learnnote-assistant/pull/268) correction
is already on main; this change completes its readiness-report coverage using
synthetic fixtures. Stored credentials, settings and existing audio-format
fallback behavior are unchanged.

## Compatibility boundary

- Only `temperature` is removable. The current builder also supplies a
  disabled-thinking control for some providers; that field is preserved, as
  are all token limits, safety fields, messages, model and client/endpoint.
- Require structured SDK status 400/422, code `unsupported_parameter`, exact
  parameter `temperature`, and its presence in the original request. Never
  classify provider prose, generic 400/422, auth, rate, network or `TypeError`
  failures as compatibility signals. A second rejection never retries again.
- Existing cancellation is checked before retry in text/visual calls. The
  grounding-repair call has no existing cancellation callback. Legacy page
  text generation, which has no audit-event sink, is outside this narrow retry.
- The existing diagnostics store only a bounded original status/code,
  allowlisted parameter/request stage and retry outcome. Raw provider bodies,
  exception text, endpoint URLs and credentials cannot enter the new event.
  Existing usage accounting records each actual attempt; no telemetry added.

## Validation

- Final integrated product tree: **1,005 guarded backend tests**, all **47 web
  test files**, all **66 extension test files**, and **157 script tests** with
  3 platform-only skips passed. Architecture checks passed 24 boundary modules,
  12 routers, 2 state domains and 28 size guards; aggregate 9,267/9,300.
- Focused coverage includes a real saved-transcript task with a deterministic
  SDK fixture for successful and failed compatibility recovery. Progressive
  batch recovery retains exactly one draft event/section per completed batch;
  cancellation and replay preserve existing successful output.
- All 11 built-in provider presets pass the offline contract with
  `network_attempted: false`. Archive bytes, OpenAPI/task schema and ordered
  operation fixtures remain unchanged.
- The create dialog and batch importer share a frozen pre-submit disclosure.
  UI tests cover stale responses and LF/CRLF rendering. Route inspection never
  constructs a provider client, starts a probe, downloads a model or submits
  a task.
- Windows Edge visual verification is pending. The bounded
  `scripts/model-route-visual-acceptance.cjs` is wired into the existing Windows
  visual gate. It fulfills assets and APIs from local synthetic fixtures and
  rejects every remote request, model probe/download and task submission. Run:
  `node scripts/model-route-visual-acceptance.cjs http://127.0.0.1:8765 build/model-route-ui`.
  Inspect its report and screenshots before claiming browser acceptance.
- No live provider or source-site requests, real credentials, private media or
  measured billing/latency experiments were used. Real inference quality and
  evidence-based cost/time ranges remain outside the proven scope of this patch;
  #146 remains open.
