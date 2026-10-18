import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import helpers from '../../scripts/installed-reading-paging-acceptance.cjs';
import diagnostic from '../../scripts/installed-diagnostic-acceptance.cjs';
import follow from '../../scripts/claim-follow-visibility-acceptance.cjs';
const { validateFeatureFixture, assertPage, assertPreview } = helpers;
const sourceVariants = url => {
  const source = fs.readFileSync(new URL(url, import.meta.url), 'utf8').replace(/\r\n/g, '\n');
  return [source, source.replace(/\n/g, '\r\n')];
};
const fixture = { community_task_id: 'caption', reading: { task_id: 'reading', title: 'Synthetic installed reading', deep_heading: 'Synthetic deep heading', claim_id: 'claim-' + 'a'.repeat(20), oversized_claim_id: 'claim-' + 'b'.repeat(20), edition_revision: 'c'.repeat(64), media_sha256: 'd'.repeat(64) } };
test('new features require the exact version, bounded known synthetic identities, and cannot apply to startup/0.2.16 diagnostics', () => {
  const args = ['out','1234','http://127.0.0.1:1235','caption','42','--expected-version','0.2.17'];
  assert.throws(() => diagnostic.parseArgs(args), /requires the old-installed feature fixture/);
  assert(diagnostic.parseArgs([...args,'--feature-fixture','fixture.json']).featureFixture);
  for(const changed of [[...args,'--feature-fixture','fixture.json','--startup-only'], [...args.slice(0,-1),'0.2.16','--feature-fixture','fixture.json']]) assert.throws(()=>diagnostic.parseArgs(changed));
  assert.equal(validateFeatureFixture(fixture,'caption'),fixture);
  for(const change of [{...fixture,community_task_id:'other'}, {...fixture,reading:{...fixture.reading,task_id:'caption'}}, {...fixture,reading:{...fixture.reading,title:'Unverified title'}}, {...fixture,reading:{...fixture.reading,claim_id:'bad'}}, {...fixture,other:1}]) assert.throws(()=>validateFeatureFixture(change,'caption'));
});
test('501 API page contracts reject inflated, duplicate-position or incomplete page metadata', () => {
  const value={task_id:'caption',enabled:true,total_count:501,limit:500,offset:500,returned_count:1,items:[{}],groups_scope:'current_page_only',has_more:false,next_cursor:null,previous_cursor:'previous'};
  assertPage(value,500,1,'caption');
  for(const change of [{total_count:500},{limit:501},{offset:0},{returned_count:2},{items:[]},{groups_scope:'all_items'},{has_more:true},{next_cursor:'invalid'},{previous_cursor:null}]) assert.throws(()=>assertPage({...value,...change},500,1,'caption'));
});
test('last-entry preview preserves exact selected text and existing model-input budgets', () => {
  const last={item_id:'last',text:'Synthetic selected text.',task_id:'caption',source_uri:'https://example.com/synthetic-rollback'};
  const value={task_id:'caption',model_request_performed:false,selected_item_ids:['last'],persisted:false,can_submit:true,opinions:[last],original_sources:[{}],limits:{opinion_items:20,opinion_characters:20000,original_source_items:24,original_source_characters:12000}};
  assertPreview(value,last,'caption');
  for(const changed of [{...value,selected_item_ids:['other']},{...value,persisted:true},{...value,opinions:[{...last,text:'Changed'}]},{...value,original_sources:[]},{...value,limits:{...value.limits,opinion_items:500}}]) assert.throws(()=>assertPreview(changed,last,'caption'));
});
test('larger source-label capture is fixture-scoped and cannot change scrolling predicates', async () => {
  for(const listTextLimit of [999,4097,Infinity,'4096']) await assert.rejects(follow.assertClaimFollowVisibility(null,{listTextLimit}),/diagnostic bound/);
  for (const source of sourceVariants('../../scripts/claim-follow-visibility-acceptance.cjs')) {
    assert.match(source,/listTextLimit = 1000/); assert.match(source,/item.before.claimListTextLength <= listTextLimit/);
    assert.match(source,/listTextLimit <= 4096/);
  }
});
test('installed extension reuses geometry and never mocks API, changes CSS, launches a browser, or runs a model answer', () => {
  for (const source of sourceVariants('../../scripts/installed-reading-paging-acceptance.cjs')) {
    for(const required of ['assertClaimFollowVisibility(page','assertOutlineHeadingVisible(geometry)','pagingViewportState','assert.equal(state.writes.length, 4)','/qa/preview','listTextLimit: 4096','requireUniqueActiveClaim: true']) assert(source.includes(required));
    assert.doesNotMatch(source,/\.route\(|route\.fulfill|addStyleTag|setViewportSize|chromium\.launch|#communityQuestionSend.*click/);
  }
});
test('added feature envelope cannot relax native dialog, input, or readback budgets', () => {
  for (const source of sourceVariants('../../scripts/installed-diagnostic-acceptance.cjs')) {
    assert.match(source, /const TIMEOUT = 15000,/);
    assert.match(source, /AddSeconds\(\$\(if \(\$c.observeOnly\) \{ 1 \} else \{ 15 \}\)\)/);
    assert.match(source, /'native Save action', timeouts.action \?\? 30000/);
  }
  for (const source of sourceVariants('../../scripts/installed-native-save-controls.ps1')) {
    assert.match(source, /ElapsedMilliseconds -ge 2000/);
    assert.match(source, /ElapsedMilliseconds -lt 2000/);
  }
});
