# Local 0.2.11 validation

## Model configuration

References inspected on 2026-09-16:

- https://api-docs.deepseek.com/guides/vision/
- https://api-docs.deepseek.com/updates/
- https://github.com/omicverse/omicos/blob/main/changelogs/webui.md

Adopt the provider/model distinction and explicit capability states described in OmicOS's public UI notes. No OmicOS credentials or private application data were copied.

The provider's actual model list supplies selectable IDs, while manual IDs remain supported. Cached lists are scoped by provider and endpoint, retained for up to one day, and contain no API key. Known DeepSeek Flash image support is labelled as documented; unknown capabilities stay unknown. An explicit image test uses only generated red/blue blocks and records successful endpoint/model checks for seven days.

Actual local DeepSeek discovery returned `deepseek-flash` and `deepseek-v4-pro`. The Flash image test passed in 1907 ms. Pro image support was not tested and is not labelled as verified. The default connection now uses Flash and retains its system-vault key.

## Grounding correction

A real source subtitle used `GBT`, while generated notes used `GPT`. Neither spelling was independently confirmed against audio. Do not whitelist or silently normalize the name. Strengthen repair instructions to preserve source spelling or omit an unsupported claim.

If a model repair still leaves only unsupported-name issues in a long plain-text note, at most two passages totalling no more than 15% of the note may be omitted. Recheck the remaining note against all existing grounding rules and insert a visible omission notice. Keep omitted passages in local audit JSON. Code, headings, tables, short notes, quantity errors and broader unsupported content cannot use this recovery.

The current Tokyo task successfully regenerated a 3207-character note with DeepSeek Flash. Its model repair passed without the omission fallback. Summary stage took 17562 ms. The saved subtitle JSON and SRT hashes remained unchanged.

Validation: 577 backend tests, 60 release-script tests, 45 desktop tests and 58 web tests passed; browser checks cover catalog selection, capability states, custom IDs, provider isolation, saved-key handling and settings persistence. Local client rebuilt as 0.2.11; GitHub stable release remains 0.2.10 until separately published.
