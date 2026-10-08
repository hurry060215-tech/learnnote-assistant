# Extension locale visual acceptance

The Windows `UI visual acceptance` workflow renders the shipped
`extension/sidepanel.html`, CSS, i18n runtime and sidepanel controller in Edge.
It runs `scripts/extension-locale-visual-acceptance.cjs`; this is a real browser
render of the extension-owned UI, not a screenshot of a mock recreation.

## Reproducible conditions

- Chinese `zh-CN` and English `en-US`.
- Physical target widths 390, 768 and 1440; target height 900.
- Effective zoom 90%, 100%, 200%: CSS viewport is physical size divided by zoom,
  with `deviceScaleFactor` equal to zoom. This is layout-equivalent viewport
  stress, **not** browser-toolbar zoom or a native Side Panel installation.
- Fresh browser context per condition; reduced motion enabled.
- Loading, connected, localized failure and completed-result captures in every
  condition. Offline and incompatible-service captures in both locales at
  390/100%. Keyboard focus and source chapter selection are exercised.
- Original synthetic course title, subtitle, note, instructions and question
  remain unchanged in both languages.

Chrome runtime, storage, tab, permission and i18n APIs are explicit test doubles.
The local-service health/task/artifact replies are also synthetic. Unexpected
remote fetches fail. There is no real Bilibili access, account, permission prompt,
model call, installed-extension claim, or private course screenshot.

## Outputs

`build/extension-locales/report.json` records the exact source SHA, browser
version, viewport/effective zoom, layout measurements, errors and stub boundary.
Each condition asserts no horizontal document/body overflow and no clipped
visible controls before writing PNGs. Four 1280×800 English/Chinese summary and
transcript screenshots are named `store-*.png`. They are truthful **candidate
store assets** from the current shipped UI and synthetic content, not a claim
that a store listing was uploaded. Both support documents and listing text
remain checked in under `extension/`.

Artifacts are uploaded with the workflow's `ui-visual-<run id>` bundle and retained
for 14 days. A green run and its report must be cited before treating the matrix
or screenshot criterion as passed. `--self-test` checks matrix/path containment
without launching a browser; it cannot substitute for rendered evidence.
