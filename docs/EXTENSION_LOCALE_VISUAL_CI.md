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
Each condition records a diagnostic PNG and asserts no horizontal document/body
overflow and no clipped visible controls.

### Separate store scenes

After the unchanged 18-condition matrix, fresh contexts render the dedicated
`scripts/extension-store-visual-fixtures.cjs` lesson in both languages. The same
authored English course title, six subtitle cues and source-linked note are
supplied to each locale, with assertions that the UI preserves the content.
The regression-only long model name and interpolation strings remain in the
matrix; they are not used in the store scenes.

Four 1280×800 English/Chinese summary and transcript compositions are named
`store-<locale>-<summary|transcript>-1280x800.png`. Each visibly identifies its
two separate panel views and its synthetic content. The left view includes the
complete app header, connection and course cards before sending. The right view
shows the complete note or transcript result card after the synthetic task.
They are faithful captures of the shipped DOM/CSS at a 576×900 viewport, arranged
side by side, with uniform scaling of at most 10%. They are not a rearranged
application layout. Framing assertions require every artwork element, including
the disclosure, to fit. No product DOM, style, label or result is overwritten for
presentation. The representative note is authored fixture data, not model output.

`store-candidates.json` records the source SHA, browser, workflow URL, fixture
hash, image dimensions, SHA-256 hashes, composition method and disclosure.
`store-source-<locale>.png`, `store-result-<locale>-<state>.png` and
`store-full-panel-<locale>-<state>.png` retain the original captures for review.
Run this offline integrity check on the downloaded artifact:

```sh
node scripts/extension-store-visual-fixtures.cjs --verify build/extension-locales
```

It requires all four output images and their source captures, matching hashes
and dimensions, and a passing 18-case extension report from the same source SHA.
It does **not** approve visual quality. The durable review/archive procedure is
in [the store asset directory](../extension/store-assets/README.md). Both support
documents and listing text remain checked in under `extension/`.

Artifacts are uploaded with the workflow's `ui-visual-<run id>` bundle and retained
for 14 days. Cite the exact extension-stage result and source SHA; disclose any
unrelated later workflow failure. The screenshot criterion additionally requires
inspection of all four actual images and a durable reviewed archive. `--self-test`
checks matrix/path containment without launching a browser;
`node extension/tests/store_scene_fixtures.test.mjs` tests fixture isolation,
original-language replies, local-only artwork and tampered-artifact rejection.
Neither offline test substitutes for rendered evidence.
