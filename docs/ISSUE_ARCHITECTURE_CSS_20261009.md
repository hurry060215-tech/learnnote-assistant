# Issue #143: classic stylesheet domain extraction

Snapshot base: `4f872044cf949266f51f8f0274b1ff46315813f3`.
Issue #143 remains open. This is one bounded 658-line extraction; the historical
entry still contains 12,262 lines and needs further work.

## Boundaries and cascade

The existing final sections have explicit, contiguous domains. Their original
comments, selectors, declarations, whitespace and nested media rules are retained:

1. `styles.css`: the first 12,262 lines of the existing classic cascade.
2. `classic-workbench.css`: 489 lines, compact source controls and the subsequent
   workbench/queue density audit overrides.
3. `classic-interactions.css`: 78 lines, stable tracks/scrollbars, task rendering,
   video sizing and reduced-motion overrides.
4. `classic-study.css`: 91 lines, local knowledge results and study controls.

`classic.html` links those four files in that order, immediately before the
unchanged `workspace.css`, `product.css`, `mature.css`, `editorial.css` and
`experience.css` links. The files stay in `web/`, preserving the relative URL
base. The extracted group currently has no `url()`, `@font-face`, `@import`,
`@namespace` or `@charset` dependencies. Font stacks and all media/container
queries are unchanged. No rule is merged, reordered, reformatted or deduplicated.

Concatenating the four files reproduces the original 231,313 UTF-8 bytes exactly
(SHA-256 `141027199167e733bd9800fe10a6e4dc50b73f9b76cf20832517696ec66c76f6`).
The snapshot test normalizes checkout CRLF to LF for Windows compatibility.

There are three additional same-origin stylesheet requests. They are ordinary,
unconditional render-blocking head links, so the browser discovers them together;
request completion order does not determine CSS cascade order. There is no
import waterfall, asynchronous stylesheet swap or change to script order. All
four links receive the same new cache version to avoid using the old full sheet
alongside the extracted suffix. Request timing can change; visual equivalence
still requires the actual Windows/Edge CI run on the published commit.

The default reader continues to load only `desk.css`. Windows and macOS
PyInstaller specs exclude all three classic modules alongside `styles.css`;
release-tree auditing rejects their accidental inclusion. Source checkout and
Docker deployments continue to serve them through the existing complete `web/`
directory. No backend, persisted data, dependency, permission, network destination
or build framework changes are introduced.

## Contracts and intentional future changes

`scripts/check-architecture.py` executes `classic_styles.py` alongside the existing
architecture gates. The latter enforces exact link order, unconditional head
loading, a shared cache version, complete file boundaries, declared module
membership, missing files, relative/root-local assets, and exclusion from the
default reader. Imports are forbidden, including self/cyclic imports: this group
has an explicitly flat load contract. New remote assets are rejected. Browser
CSS parsing remains the responsibility of Edge, not the small resource scanner.

The old entry ceiling is tightened from 12,920 to 12,262. Each extracted module
has its exact current line ceiling (489 / 78 / 91), and the complete four-file
group has an independent 12,920-line ceiling. Existing runtime and historical CSS
budgets are unchanged; all four siblings remain included in the historical sum.

`scripts/tests/fixtures/classic_styles_v1.json` records independent pre-extraction
provenance and content. For a later intentional style change, review the actual
rule/cascade diff, update the snapshot digest/byte/line values and provenance with
an explanation of that change, keep per-module and aggregate ceilings enforced,
and rerun the architecture/static/Edge gates. Do not regenerate the snapshot to
hide an unexplained refactor difference, relax limits, minify declarations or move
growth to an uncounted file. Further extraction should retain a truthful combined
budget and a documented semantic boundary.

## Verification and rollback

Local checks use synthetic fixtures and need no browser, user data or network:

```sh
python scripts/check-architecture.py
python -m unittest scripts.tests.test_classic_styles scripts.tests.test_release_tree scripts.tests.test_web_accessibility scripts.tests.test_ui_visual_contract scripts.tests.test_architecture_graph scripts.tests.test_javascript_graph
node --check scripts/accessibility-visual-acceptance.cjs
```

The local architecture command, all 49 focused Python tests, all 44 Web test
programs, the visual-script syntax check and `git diff --check` passed. A separate
comparison against the original Git blob also confirmed exact byte equality.

Run the Web test programs, including the full classic Markdown harness and CSS
clarity contracts; they now read the complete extracted group. The existing
`UI visual acceptance` workflow runs the default reader gates and classic
accessibility/learning matrix on Windows/Edge. The classic accessibility script
additionally checks every linked sheet loaded, parsed to nonempty CSS rules and
occupies its expected cascade position before testing locales, keyboard focus,
200% scale and desktop/tablet/mobile widths. Local visual execution is not claimed.

Rollback is an ordinary revert of this extraction, including its HTML links,
guards and release exclusions. No migration or data rebuild is needed. The large
remaining classic cascade, other monolithic frontend/backend files, and broader
issue #143 acceptance remain separate work.
