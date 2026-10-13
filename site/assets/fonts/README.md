# Website typography

`learnnote-site-sans.woff2` is a self-hosted character subset of Google's
[Noto Sans SC variable font](https://github.com/google/fonts/tree/main/ofl/notosanssc),
distributed under [SIL Open Font License 1.1](OFL.txt). The original copyright
notice and license are included. The subset family is named `LearnNote Site Sans`.

- Downloaded: 2026-09-08.
- Original file: `NotoSansSC[wght].ttf` from the official Google Fonts repository.
- Original SHA-256: `a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da`.
- Subset SHA-256: `6fff1b03aea6e3f00c90527ee7946160522f9b45afd7a2e587bee000e2bc250f`.
- Coverage: text in the website HTML pages and printable ASCII; 572 distinct
  input characters, 178,424 bytes. New characters fall back to system fonts.
- Build: fontTools subset, all layout features retained, WOFF2/Brotli, variable
  weight axis retained. Family/full/PostScript names were changed to the subset
  family. Only codepoints used by the website are included, not arbitrary notes.

The website serves the font from its own assets. Visitors do not contact a
third-party font CDN. Font software retains OFL licensing independently of the
application's Apache-2.0 license. Do not reuse this limited subset as the app's
general-purpose user-content font.

## Quiet-reading alignment, 2026-10-13

The landing page and both policy pages share this subset first, then the app's
sans-serif fallback order: Noto Sans SC, Noto Sans CJK SC, PingFang SC, Microsoft
YaHei UI, Microsoft YaHei, Segoe UI, system-ui, sans-serif. The app must not use
this limited website subset for arbitrary user content. The original font file,
license, and hash above are unchanged.

The current HTML coverage audit finds these existing missing glyphs:

- Landing and security: `脚`.
- Privacy: `仅余共历史呼态按旧状盖称稿空绑脚草表覆订输量链随预额` (26 glyphs).

Those characters use the explicit system fallback. This is not a claim that the
subset covers every current page. The website acceptance script records both
computed CSS typography and actual Chromium/Edge platform font names and glyph
counts via `CSS.getPlatformFontsForNode` in its JSON report. Its unavailable-font
case verifies that the primary heading and download route still work without the
local font. No third-party font request is introduced.
