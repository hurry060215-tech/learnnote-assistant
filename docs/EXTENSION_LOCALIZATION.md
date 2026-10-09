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

### Store asset acceptance remains pending

Four later candidates from source `e46d224967c42649de1680bb4acafc8aef17694d`
were inspected and rejected as store material: the app header/course context was
cropped away and the images showed regression-only placeholder content.
[Run 37938043910](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37938043910)
and [artifact 11620640482](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37938043910/artifacts/11620640482)
contain that evidence. The extension stage passed; a later unrelated concept
fixture failed. The source SHA is GitHub's test merge commit.

Dedicated store scenes now use one representative synthetic course in both UI
languages. Four 1280×800 compositions show separately labeled, complete source
and result views, with visible demo disclosure and original captures/hashes for
review. The existing layout/error/original-content matrix remains unchanged.
See [reproduction details](EXTENSION_LOCALE_VISUAL_CI.md) and the
[review/archive checklist](../extension/store-assets/README.md).

**Issue #144 remains open until the replacement images are rendered, visually
reviewed and persistently archived.** Offline fixture tests and generated image
hashes are not visual approval. Native extension installation and browser
permission prompts are separate, untested boundaries. Store upload is not a
dependency of this localization issue, and no upload is part of these scenes.
