# Shared Unicode publication gate (#150)

Imported text, transcript quality reports and formal Markdown now share the
same corruption signatures and blocking threshold. A single high-confidence
artifact such as `锟斤拷` or `鏂囧` in prose requires review; it no longer slips
through a lower decoder score. Individual CJK and accented characters are not
evidence of corruption. In particular, the legitimate character `閫` is no
longer sufficient to block a note.

Explicit Markdown code fences, indented code and matched inline backtick spans
are quoted data and excluded from this prose gate. Their literal diagnostic
strings and ASR-term examples are retained. Unmatched or escaped inline
delimiters do not hide surrounding prose. The new CJK signatures do not trigger
automatic word replacements. Existing reversible UTF-8 repairs remain supported
when they can run without recoding quoted code.

Unresolved transcript artifacts retain their text and enter the existing
`draft.review.md` path before summarization. Raw transcript artifacts are not
rewritten, and the result is explicitly marked as requiring review. Existing
sparse local-ASR uncertainty marking and the strict replacement-character
failure boundaries remain in place.

Preserved OCR or legacy evidence is also checked when proposing or saving new
study cards. Known corruption cannot bypass the import gate through previously
indexed text. Existing evidence and cards are not rewritten or deleted.

Direct subtitle downloads now pass the HTTP-declared charset to the strict
decoder. An incompatible declaration fails without overwriting previously
saved subtitle artifacts. BOM precedence remains unchanged. Subtitle
`.decode.json` files additionally retain all `DecodedText` metadata except the
text itself: encoding source/confidence, declared encoding, repair flag,
corruption score, replacement-character count and normalization version, as
well as the existing encoding, digest and byte count. This is additive metadata;
the sidecar schema version and original byte files are unchanged.

The synthetic corpus in `backend/tests/fixtures/unicode_gate_20261009.json`
checks both blocked and legitimate text across byte decoding, TXT/Markdown
import, segmented/full transcript reports and formal-note normalization.
`test_shared_unicode_gate.py` also checks the actual saved-transcript review
path without model calls. `test_subtitle_decode_provenance.py` uses mocked HTTP
responses to check charset conflicts, byte retention and complete sidecars.

This is a conservative gate for known encoding artifacts, not a language or ASR
accuracy detector. Code exemptions require explicit Markdown syntax; arbitrary
unmarked strings cannot be inferred to be intentional code examples.
