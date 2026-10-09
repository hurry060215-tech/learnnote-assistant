# Extension localization acceptance (#144)

## Resource and runtime contract

`extension/_locales/zh_CN/messages.json` and `extension/_locales/en/messages.json`
are the source of truth. The manifest uses `default_locale: zh_CN` and localized
name, description, and action title. The panel follows the browser UI language;
English variants select English, and unsupported locales use Simplified Chinese.

- Use `t("key", { parameter: value })` for runtime product copy.
- Use `data-i18n`, `data-i18n-aria`, `data-i18n-title`,
  `data-i18n-placeholder`, or `data-i18n-alt` for owned HTML text/attributes.
- Keep markup out of resource messages. Escape translated text inserted into HTML.
- Named placeholders must match in both catalogs. Values are interpolated once;
  user text is never treated as a resource key or recursively interpolated.
- Never put translation ownership on a container holding user-authored content.
  Titles, subtitles, notes, questions, answers, model names, and extra instructions
  remain unchanged. There is no automatic translation or DOM-wide text replacement.
- Known extension/background errors are localized at the panel's product-error
  boundary. Unknown backend/provider diagnostics are retained verbatim, including
  their original language. New product errors should receive stable resource keys;
  do not try to infer or translate arbitrary diagnostic/user text.

After editing catalogs, run `python scripts/audit-i18n.py --write-runtime` to
regenerate the two bundled fallback catalogs in `extension/i18n.js`. The normal
CI audit checks the bundle against its sources and does not silently regenerate.
Chrome messages are preferred; absent/throwing APIs use the bundled locale and
then the default Chinese catalog. No fetch, account, model, or permission is
needed to translate the extension.

## Automated checks

- `python scripts/audit-i18n.py`: manifest, all panel HTML/ARIA/title/placeholder/
  alt keys, runtime calls, native-error aliases, locale parity, interpolation
  parity, runtime fallback parity, script order, hardcoded-copy guard, and known
  background/content error resource coverage.
- `python -m unittest scripts.tests.test_i18n_audit`: deliberately missing runtime
  and HTML keys, unlocalized Chinese/English copy, accessibility attributes,
  nested template strings, interpolation mismatch, stale fallback and bad load
  order fail the guard. Newly introduced background/content error copy without
  a matching service resource also fails. The scanner is a lexical copy guard, not a JS parser;
  Node syntax checks and UI review remain required.
- `node extension/tests/i18n_runtime.test.mjs`: English and Chinese resources,
  unsupported locale/API fallback, static and dynamic copy, accessibility labels,
  placeholder preservation, connection errors, mode changes, permission denial,
  known service errors, and original title/note/subtitle preservation.
- Existing extension tests remain required, including handoff, permission-race,
  protocol, source-change, and recovery tests.

## Support and store assets

Both support documents are present: [English](../extension/HELP.en.md) and
[简体中文](../extension/HELP.zh-CN.md). Both listing descriptions are in
[STORE_LISTING.md](../extension/STORE_LISTING.md).

### Actual rendered checkpoint

At commit `fd8491747ff555c1ac8c7e92dcaad0c09762d0e8`, Windows Edge rendered the
shipped panel and its actual controller/styles in both locales. The extension
runner reported **18 passed conditions and four generated store candidates**:
390/768/1440 target widths × 90/100/200% effective viewport/device scale × two
languages. It exercised loading, connected, localized error and result states,
with additional offline/incompatible checks at 390/100%. User content stayed
original. Chrome APIs and local-service responses were synthetic; the UI was real.

Evidence: [workflow run 37802466976](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37802466976),
[artifact 11560713522](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37802466976/artifacts/11560713522).
The extension stage passed; the whole workflow subsequently failed on a separate
default-reader 390/200% overflow. See [reproduction conditions](EXTENSION_LOCALE_VISUAL_CI.md).

**Issue #144 remains open.** The PNGs have not been manually inspected and are
not persistently archived as approved store assets. The available CI artifact
has 14-day retention; its image bytes could not be read in this cloud task
(HTTP 403), and that boundary was respected. Generated screenshots and automated
layout assertions are evidence of rendering, not visual/store-submission approval.
Native extension installation and browser permission prompts were not tested.
No artifact transfer workaround, new permission or store upload is part of this
patch. Matching reviewed, durable bilingual assets remain a separate prerequisite.
