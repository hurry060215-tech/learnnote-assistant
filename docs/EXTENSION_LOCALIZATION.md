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

### Reviewed and archived acceptance (2026-10-09)

[Windows Edge run 37941628048](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37941628048)
passed, including all 18 extension locale/viewport/effective-scale conditions,
and produced four 1280×800 store compositions. Source
`a400df83e450004253d6386847a1bfc5a473e00e` is GitHub's test merge of
`179ea5cdb394476ec3eda87da8abf4f0591b88e4` and PR #273 head
`413fa0d5ccd8e4c7c8e9ab812863e986ded9841e`; its tree
`081304e04b7da91a894e379fb0bc0b38f3cb399c` equals that tested head's tree.

At 2026-10-09 14:12:58 UTC, Codex performed an **AI assistant visual review**
of all four artwork images and all four full-panel captures individually at
original resolution. Product labels match each locale; text and timestamps are
readable; complete source/result context and the separate-view/synthetic-data
disclosure are visible; the same English lesson remains unchanged.

The [durable image archive](../extension/store-assets/README.md) includes all four
listing images, ten raw captures, the unchanged
[capture manifest](../extension/store-assets/a400df83e450004253d6386847a1bfc5a473e00e/store-candidates.json),
[passing report](../extension/store-assets/a400df83e450004253d6386847a1bfc5a473e00e/report.json),
and a separate [review record](../extension/store-assets/a400df83e450004253d6386847a1bfc5a473e00e/review.json)
with image hashes and official artifact provenance. The generated manifest stays
`candidate-unreviewed`; the separate record documents the subsequent review.

### Original issue #144 criteria

1. **Manifest default locale:** `extension/manifest.json` declares `zh_CN` and
   localized name, description and action title. The i18n audit enforces this.
2. **Product UI, errors and accessibility switch/fallback:** both catalogs have
   273 matching keys. `i18n_runtime.test.mjs` exercises English, Chinese,
   unsupported-language and unavailable-message/API fallbacks, dynamic statuses,
   known errors, ARIA/title/placeholder labels and permission-denial copy.
   Unknown provider diagnostics remain verbatim by design.
3. **Corresponding screenshots and support documents:** both locales have
   reviewed summary/transcript artwork in the durable archive, bilingual listing
   copy in `STORE_LISTING.md`, and `HELP.en.md` / `HELP.zh-CN.md`.
4. **Original content preserved:** runtime tests and store-fixture assertions
   retain titles, notes, subtitles, questions and instructions. The actual reviewed
   images preserve the same authored English lesson in both UI languages.
5. **390/768/desktop layout without overflow:** the archived passing report
   covers 390/768/1440 target widths × 90/100/200% effective viewport/device scale
   × two locales. It checks document/body/control geometry in loading, connected,
   error and result states, plus offline/incompatible states at 390/100%.
6. **Zero missing keys and new copy in resources:** `scripts/audit-i18n.py`
   reports zero missing keys, catalog/placeholder mismatches, hardcoded product
   copy and unlocalized known service errors. CI runs this guard; negative tests
   in `scripts.tests.test_i18n_audit` require missing/new hardcoded copy to fail.

The repository evidence covers all six criteria. Protected PR checks and merge
remain the publication gate before issue closure. This asset acceptance does
not claim native extension installation, real Chrome/Edge permission-dialog
testing, native toolbar zoom, real model generation or store approval/submission.
Those boundaries are separate; automatic store upload is explicitly not a
dependency of #144. See [reproduction conditions](EXTENSION_LOCALE_VISUAL_CI.md).

### Historical rendered checkpoint

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

### Superseded store candidates

Four later candidates from source `e46d224967c42649de1680bb4acafc8aef17694d`
were inspected and rejected as store material: the app header/course context was
cropped away and the images showed regression-only placeholder content.
[Run 37938043910](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37938043910)
and [artifact 11620640482](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37938043910/artifacts/11620640482)
contain that evidence. The extension stage passed; a later unrelated concept
fixture failed. The source SHA is GitHub's test merge commit.

These rejected images are superseded by the reviewed archive above. The
dedicated store scenes leave the existing layout/error/original-content matrix
unchanged and do not use its regression-only stress placeholders.
