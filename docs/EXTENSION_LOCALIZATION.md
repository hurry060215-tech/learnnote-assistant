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

The screenshot and visual-review acceptance items are **not complete**. No new
browser screenshot or 390/768/desktop overflow result was produced in the current
cloud task: its supported localhost browser route was blocked. Node DOM stubs do
not prove pixel layout. Do not use this document as store-submission approval.

Before closing #144 or publishing the updated listing, capture real extension
screenshots with synthetic, non-private course material in each browser locale:

| Capture | English caption | 简体中文说明 |
| --- | --- | --- |
| Connected panel | Current source and processing choices | 当前来源与整理方式 |
| Original transcript | Search and revisit the original video | 搜索原文并回到视频 |
| Permissions | Site authorization and local data flow | 站点授权与本机数据流 |
| Failure/recovery | Clear local-client recovery steps | 清楚的本机连接恢复步骤 |

For **each locale**, inspect widths 390, 768, and 1440 pixels (or a recorded
actual desktop width), expanded source/options/permission sections, long page
and model names, keyboard focus, loading/offline/incompatible/error states, and
200% text. Record `scrollWidth <= clientWidth` for the panel, not only its parent
page, and inspect clipped labels and controls visually. Store screenshots with
locale and width in the filename; the expected files are intentionally not
represented as existing until captured.
