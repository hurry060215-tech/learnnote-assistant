import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const context = vm.createContext({ URL });
for (const key of ['document', 'window', 'localStorage', 'fetch', 'chrome']) {
  Object.defineProperty(context, key, { get() { throw Error(`Pure visual projection touched ${key}`); } });
}
vm.runInContext(readFileSync(new URL('../task-format.js', import.meta.url), 'utf8'), context);
vm.runInContext(readFileSync(new URL('../visual-window-evidence.js', import.meta.url), 'utf8'), context);
const domain = context.LearnNoteVisualWindowEvidence;
assert(Object.isFrozen(domain));
const fixtures = JSON.parse(readFileSync(new URL('./fixtures/visual-window-bb47c6f.json', import.meta.url), 'utf8'));
for (const row of fixtures) {
  const before = JSON.stringify({ window: row.window, transcript: row.transcript });
  for (const name of ['visualStudyCueHtml', 'visualWindowSummaryItems', 'visualWindowSummaryHtml',
    'visualWindowCueSegments', 'visualStudyChecklistHtml', 'visualStudyCheckpointHtml', 'visualStudyQuestionHtml']) {
    assert.deepEqual(JSON.parse(JSON.stringify(domain[name](row.window, row.transcript))), row.expected[name], `${row.name}: ${name}`);
  }
  const segments = row.transcript?.segments || [];
  assert.equal(domain.transcriptLines(segments), row.expected.transcriptLines);
  assert.deepEqual(segments.map(segment => domain.segmentOverlapsWindow(segment, row.window)), row.expected.overlaps);
  assert.equal(JSON.stringify({ window: row.window, transcript: row.transcript }), before);
}
const hostile = fixtures.find(row => row.name === 'hostile-html');
assert(!domain.transcriptLines(hostile.transcript.segments).includes('<svg'));
assert(domain.visualWindowSummaryHtml(hostile.window).includes('&lt;img'));
assert.deepEqual(JSON.parse(JSON.stringify(domain.visualWindowCueSegments({start:0,end:20}, fixtures.at(-1).transcript, 0))), []);
console.log(`Visual window domain preserves ${fixtures.length} frozen original projections/HTML outputs without browser effects or input mutation`);
