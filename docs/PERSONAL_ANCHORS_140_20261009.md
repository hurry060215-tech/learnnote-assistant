# Personal evidence anchors: bounded issue #140 increment

This change extends the existing local annotation layer and its existing editor.
It does not rewrite generated notes, call a model, introduce a second editor, or
use real user data in verification.

## Behavior

- A personal annotation can reference a current generated claim, an exact
  subtitle cue or contiguous run of up to 1,000 cues, or one visual window. The existing text-selection
  anchor remains available for tasks and materials.
- Each explicit target includes its source task, artifact revision and exact
  content fingerprint. Subtitle identity includes both endpoints and its full
  text; a visual fingerprint also includes its task-owned grid bytes.
- The subtitle picker selects the first and last cues. The server constructs
  the interval, retaining every included cue's ID, start/end and full-content
  hash, including overlapping cues. The outer interval covers their original
  minimum start and maximum end. It does not infer word timing or clip cues.
  Missing/invalid intermediate cues cannot be skipped. Single-cue identities
  and the schema-2 envelope stay unchanged; multi-cue anchors add a `cues` array.
- A regenerated interval resolves only if its complete ordered cue sequence is
  intact and unique within the established task family. Changed text, timing,
  order or intervening cues require repair; duplicate exact sequences are
  ambiguous after regeneration. Original records remain read-only during
  resolution. Forged or altered endpoints are rejected instead of narrowed.
- Reads resolve an unchanged target, or a unique identical target within an
  explicitly stored task-version family. A changed artifact with duplicate
  identical targets, missing evidence, changed frames or unrelated task is not
  guessed. It is shown as needing repair. Task lineage has cycle/depth guards.
- Resolution is a read-only projection. The original annotation ID, literal
  user text, quote and original anchor remain in the saved file until the user
  explicitly chooses another target and saves.
- The existing annotation form has a compact type/target selector. Its repair
  action uses the same editor. Stale editor revisions return a conflict and
  retain the draft. A lost successful create response can be retried with the
  same request ID without another annotation. Legacy clients remain readable;
  optimistic edit protection applies when the client supplies its revision.
- User text and quotes keep leading/trailing whitespace, LF/CRLF, code-like text,
  decomposed Unicode and emoji. Displayed personal text is marked as user content
  so static UI translation cannot rewrite it. No model path reads or edits it.

## Storage, export and Obsidian

The existing `personal-notes/<source-family>.json` envelope becomes schema 2 only
on an explicit save/delete/restore write. Reading schema 1 does not migrate or
rewrite it. Unchanged records keep their IDs and fields. Backups keep literal
text and typed anchors; restore merges missing IDs without overwriting current
edits. This is not a bulk migration of historical files.

Ordinary task bundles still omit personal data. The explicit
`include_annotations=true` option adds a separate `personal_annotations.json`
sidecar with schema 2, task ID and annotations. `note.md` remains generated-only.
Existing document/Markdown export choices continue to control personal additions.

The local Obsidian importer opts in on its existing bundle request. It creates
JSON mappings and readable Markdown snapshots in `Personal annotations/`, linked
from the imported note. It never replaces or deletes those snapshots. Identical
retries reuse identical files; a local edit or filename collision creates a
separate version and a visible preservation notice. Missing/invalid sidecars
retain the previous snapshot. Local Obsidian edits are not sent back to LearnNote.
The existing personal section also retains its exact trailing whitespace and
legacy content outside generated markers.

## Artifact and error boundaries

Target enumeration reads only direct task-owned note/transcript/index files and
image files inside that task's `grids` directory. It rejects symlink/outside-task
paths, limits artifact bytes, and hashes grids in bounded chunks. An unreadable
artifact does not rewrite the annotation file. Public annotation API errors use
fixed known codes or a generic fallback, never filesystem paths or exception
bodies.

## Rollback

Older versions can display personal text, but their save/restore field whitelist
can remove typed anchors and their text trimming can alter edge whitespace.
Older editors therefore do **not** provide a lossless schema-2 roundtrip. Preserve
a schema-2 backup/export snapshot before using an older editor, and avoid editing
or restoring that newer data with the older version. Existing schema-1 files are
left in place until an explicit write; no database migration needs reversing.

## Acceptance evidence and remaining limits

| Original #140 criterion | Evidence and boundary |
| --- | --- |
| Personal/generated storage separation | Existing source-family storage tests plus the opt-in bundle test; generated bytes remain separate. |
| Regeneration/upgrade/restore preservation | Synthetic parent/child migration, schema-1 non-mutating reads, exact text/ID backup roundtrips and non-overwriting restore. |
| Claim/subtitle/visual anchors | Current typed-target API and picker; overlap, changed-frame and duplicate-caption tests. Adjacent multi-cue intervals are covered by API, preservation, regeneration and picker-race tests; the extended actual Edge/backend acceptance passed in the final #284 CI run. |
| Visible orphan repair | Existing editor plus explicit status/repair messages; picker/submit race tests and an actual Edge/backend fixture below. That browser fixture passed on the final #284 tree; native Obsidian remains separate. |
| Generated-only or personal export | Existing export switches plus generated-only default and opt-in JSON sidecar tests. |
| Obsidian mapping and preservation | The production importer implementation is bundled for tests with synthetic ZIPs and an in-memory vault; retries, conflicts, interruption, older/malformed bundles, exact LF/CRLF and stable IDs. TypeScript and production bundle builds pass. A native Obsidian host was not run; no real vault was written. |
| No silent i18n/model rewrite | Protected personal DOM nodes and literal storage; no new model call or personal-to-model transmission. |

Material anchors continue to use the existing selected-text mechanism. Stale or
older claim maps are not rebuilt automatically. A deleted intermediate lineage
whose family can no longer be established remains orphaned. The classic editor
can retain typed anchors during text edits but the new picker belongs to the
active desk UI. These boundaries mean this increment alone is not a claim that the entire epic
is complete, even after the actual Edge/backend fixture passes.
Direct edits inside Obsidian's generated note region remain regenerable under the
existing importer contract; personal snapshots and the designated personal
section are preserved. Such generated-region edits are not automatically promoted
into annotations by this increment.

## Adjacent-cue regression and verification scope

The original #140 criterion is “可锚定 claim、字幕时间段和视觉窗口”. At base
`45e21e906b6068bfadca38a00ed37d4aee3bbc7b`, the synthetic transcript offered only
1–5s and 3–7s individual targets. Submitting the first target with `end: 7`
returned HTTP 200 but silently saved 1–5s. The regression now returns HTTP 409;
selecting both exact cues produces a separate 1–7s interval with both complete
cue identities. A stale picker or save also returns an explicit conflict.

`backend/tests/test_personal_intervals.py` covers that reproduction, unchanged
single-cue behavior, overlap, bounded selection, full-content hashes beyond the
preview, unique related-task migration, duplicate/interior/missing-cue orphans,
literal text and ID preservation, lossless backup/restore and opt-in bundles.
The actual importer is exercised with synthetic ZIPs and an in-memory vault,
including the nested interval mapping and preservation of local edits.

The existing Edge acceptance script now selects, saves, invalidates and repairs
a multi-cue interval through the real backend. It passed in the
normal Windows CI workflow for #284; it was not run in the cloud browser. Native Obsidian
execution and real-vault sync remain unverified. Arbitrary sub-cue word or
millisecond selection and reverse synchronization of Obsidian edits are outside
this bounded change.

## Verification

Run the standard offline backend runner, the web Node tests, the architecture
gate and the Obsidian plugin's `npm run verify`. Focused backend coverage is in
`backend/tests/test_personal_anchors.py` and `backend/tests/test_personal_intervals.py`; focused UI behavior is in
`web/tests/personal_anchors.test.mjs`.

For actual Windows Edge acceptance, first create the bounded synthetic fixture:

```powershell
python scripts/personal-anchors-fixture.py
$env:LEARNNOTE_DATA_DIR = (Resolve-Path build/personal-anchors-acceptance/data).Path
$env:ORT_DISABLE_TELEMETRY = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18930
# In a second shell after the backend is ready:
node scripts/personal-anchors-acceptance.cjs http://127.0.0.1:18930
```

The Edge fixture uses the actual backend. It checks all three target kinds,
overlapping subtitle selection, orphan repair, a stale edit, lost-response retry,
literal text and user-content boundary markup. The actual localization engine's
exclusion is exercised by the Node behavior test. The fixture disables automatic
release checks in its dedicated synthetic data directory. It modifies only its synthetic generated
note, and writes a screenshot/report under `build/personal-anchors-acceptance/`.
It was authored and syntax-checked in the cloud; it was not launched through the
previously denied local-browser route.

## Final integrated CI evidence

[PR #284](https://github.com/hurry060215-tech/learnnote-assistant/pull/284)
merged at `1ede8b09e259033872dc285d1c17a67671ecd7dc`. Its final head
`10f5c8d50d735d38bf9d82773cde449f2dd9e2a9` passed all seven workflow groups;
detailed CodeQL reported no new alerts and review threads were clear.
The actual Edge/backend acceptance passed in
[UI run 37974949265](https://github.com/hurry060215-tech/learnnote-assistant/actions/runs/37974949265),
using Edge 153.0.4234.48. All seven triggered main workflows also passed.

The final integrated local tree passed 1,131 guarded backend tests, 246 Node
entries, and 218 script/desktop tests (four existing skips). Exact-head plugin
CI passed 22 importer tests, TypeScript and the production bundle check. No
manual inspection of the new screenshot, native Obsidian execution or real-vault
sync is claimed. See the [follow-through record](qa/20261009-followthrough.md)
for image and broader acceptance boundaries.
