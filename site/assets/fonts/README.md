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
