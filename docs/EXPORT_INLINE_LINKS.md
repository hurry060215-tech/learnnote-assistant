# Inline links in portable exports

DOCX, PDF and HTML use the same local CommonMark token projection for inline
links. Escaped brackets/backslashes, balanced label text, code/emphasis inside
labels, escaped or balanced destination parentheses, and optional link-title
syntax are recognized by the pinned `markdown-it-py` parser. Optional titles
are parsed without becoming part of the destination or visible body; this does
not promise a viewer-specific hover tooltip. Hyperlink labels remain editable
plain text; surrounding bold/italic emphasis is retained.

The source Markdown and task metadata are never rewritten. Existing native
Word/PDF code and limited dollar-math rendering remain local. Timecode insertion
does not enter existing links, images, code or math, including links wrapping
within one nonblank prose run. Blank paragraphs and structural code boundaries
end that run.

The parser's HTML, automatic URL linking and typographic rewrites are disabled.
Its output is tokens, never executable or library-rendered HTML. Each renderer
continues escaping text and applying the existing public HTTP(S)/owned-heading
anchor checks. Unsupported schemes, private hosts and credential-bearing URLs
do not become active links. Parsing and export never fetch a linked resource;
image embedding still requires an indexed task-owned file.

URL normalization preserves the existing Unicode anchor and destination
contract. This does not disable the parser's URL validation or the export URL
checks. Parser state is request-local; there is no document cache. The existing
block/table renderer and reference-style link definitions are outside this
bounded change. CommonMark's configured nesting bound still applies.

Runtime versions are pinned in the base requirements and Windows lock:
`markdown-it-py` 4.2.0 and `mdurl` 0.1.2. Both are MIT-licensed; the frozen Windows
and macOS specs collect their package metadata and bundled upstream licenses.
See [third-party notices](../THIRD_PARTY_NOTICES.md), the
[parser documentation](https://markdown-it-py.readthedocs.io/en/latest/using.html)
and its [security guidance](https://markdown-it-py.readthedocs.io/en/latest/security.html).

`backend/tests/test_export_inline_links.py` checks actual DOCX relationships,
PDF annotations and HTML anchors, rejected URLs, multiline timecode protection,
owned anchors, concurrent parse isolation and large synthetic link sequences.
Run it through `scripts/test-backend-offline.py` alongside existing export,
claim-citation, Unicode and nested-layout contracts.
