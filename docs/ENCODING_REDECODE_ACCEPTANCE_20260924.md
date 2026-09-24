# Existing material re-decode acceptance

- Date: 2026-09-24
- Related issue: [#150](https://github.com/hurry060215-tech/learnnote-assistant/issues/150)
- Related PR: [#209](https://github.com/hurry060215-tech/learnnote-assistant/pull/209)
- Source: constructed GB18030 text fixture in an isolated local data directory; no user documents or credentials.

The browser flow imported the GB18030 fixture while deliberately selecting Big5, confirmed the displayed text was not the intended text, opened the material's encoding panel, and re-decoded the existing material with GB18030. The same material ID and anchor IDs remained in place, the rendered text and canonical evidence updated, and the downloaded original file SHA-256 stayed `266f1c9795c6478f3d461cfd0ad4a2c9ca801945ad20a788ed86e480c82a85fc` before and after the action.

The server update is a single SQLite transaction for the material's current evidence anchors and library metadata. The original source file is integrity-checked before decoding and is never rewritten. Previous anchor IDs are retained for existing FSRS cards; if a re-decode creates fewer sections, unreferenced old anchors remain available to existing cards.

## Reproduction and checks

- Windows / Microsoft Edge; Playwright browser script `scripts/encoding-redecode-acceptance.cjs`.
- Backend bound to `127.0.0.1:18782`; `LEARNNOTE_DATA_DIR=build/encoding-redecode-e2e3-data`, an isolated temporary corpus.
- Full UI import → incorrect explicit encoding → material read → re-decode with GB18030 → verify anchors and byte-for-byte source preservation passed; no browser page errors.
- Backend regression: `D:\learnnote-assistant\.venv\Scripts\python.exe -m unittest discover -s backend/tests -p test_material_redecode.py -v` — 1 passed.
- Web contract: `node web/tests/material_redecode.test.mjs` — passed.

The UI and backend re-decode action supports text materials with retained original bytes. PDF re-decoding is intentionally rejected because encoding changes do not repair image-only pages; those require local OCR. Continue to keep #150 open until the broader source and export matrix is reviewed and merged.
