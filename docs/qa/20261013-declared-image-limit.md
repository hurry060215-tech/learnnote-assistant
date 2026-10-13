# Declared image-count batching (#146)

## Source and exact scope

Checked on 2026-10-13: [Groq's official vision documentation](https://console.groq.com/docs/vision), specifically the supported-model heading, Images per Request section, Chat Completions instructions, and curl endpoint.

- Model: `qwen/qwen3.8-27b`.
- API: `chat.completions`.
- Full endpoint: `https://api.groq.com/openai/v1/chat/completions`.
- Official count declaration: “You can process a maximum of 3 images.”
- Capability catalog revision: 2. This is a dated documentation declaration, not a live service test or a measured model-quality result. A successful one-image probe does not verify the count ceiling.

Only that exact base endpoint and model inherit this rule. A trailing slash is accepted; aliases, proxy endpoints, other paths, query parameters, user info, ports and other APIs remain unknown. Existing saved models and provider presets are not changed. No expiry interval is invented for this static declaration; future official changes require a reviewed catalog revision.

## Behavior and acceptance

The settings preflight reads the saved batch preference and uses the same count plan as execution and diagnostics. Four selected image windows become batches of three and one; eight become three, three and two. A smaller requested size remains smaller. The existing selection ceiling and original window IDs remain unchanged. Missing images remain explicitly identified, without renumbering later windows.

The final image payload is checked across all messages before dispatch, including the bounded sampling-parameter compatibility retry. Cache identities include the effective partition and its prompts/windows. Completed batches can be reused after cancellation or a later batch failure; missing batches alone are requested again. Partial failures remain visible in the final merge prompt.

Offline tests use synthetic files and a provider stub to inspect actual request arguments, callbacks and cache writes. They do not contact Groq or assess the model's output quality. The Edge acceptance fixture uses the actual local planner's declaration and inspects desktop/mobile, light/dark settings rendering with all network requests intercepted locally.

Local validation: 1,653 guarded backend tests; 142 JavaScript test files; 184 script tests (three platform skips); 28 desktop tests. The new count-limit suite contains 15 tests. Independent review exercised 98 related tests. Architecture and localization checks passed. PowerShell syntax and actual Edge rendering require the Windows CI gate; they are not claimed as local Linux passes.

## Remaining limits

This patch enforces image count only. Request bytes, dimensions, context/token budgets, provider availability, prices, real quality and the four-hour source-video acceptance remain unverified. Unknown endpoints are not assigned an inferred ceiling. #146 remains open for its broader acceptance requirements.
