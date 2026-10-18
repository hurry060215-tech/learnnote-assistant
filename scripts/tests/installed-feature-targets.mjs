// Inputs come from the source rehearsal's real import/retry/claims APIs. No map
// construction or response interception here; use the shipped selector itself.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { activeClaims, claimTimelineModel } from '../../web/claim-timeline.js';

const fixtures = JSON.parse(readFileSync(0, 'utf8')), results = [];
assert.deepEqual(Object.keys(fixtures).sort(), ['ambiguous', 'corrected']);
for (const [name, { reading, edition, mapped }] of Object.entries(fixtures)) {
  const model = claimTimelineModel(mapped, { taskId: reading.task_id, text: edition.text, revision: edition.revision });
  assert(model, 'Real persisted mapping must match the saved edition');
  for (const [time, expected] of [[12, reading.claim_id], [25.01, reading.oversized_claim_id]]) {
    const active = activeClaims(model, time), intended = active.find(entry => entry.claim.claim_id === expected);
    assert(intended && intended.claim.verification === 'direct' && intended.claim.evidence_ids.length);
    if (name === 'ambiguous' && time === 12) {
      assert.equal(active.length, 2);
      assert.equal(active[0].claim.text, 'First synthetic source supports reading.');
      assert.equal(active[0].claim.verification, 'located_only');
      assert.deepEqual(active[0].targets.map(target => [target.start, target.end]), [[0, 10], [10, 20]]);
      assert.equal(active[1], intended);
    } else assert.deepEqual(active.map(entry => entry.claim.claim_id), [expected]);
    results.push({ name, time, intended: expected, active: active.map(entry => ({
      id: entry.claim.claim_id, verification: entry.claim.verification,
      ranges: entry.targets.map(target => [target.start, target.end]),
    })) });
  }
}
console.log(JSON.stringify({ passed: true, results }));
