/* Real Edge + actual local relation APIs; all source materials are synthetic. */
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
module.exports = async function ({page, api, base, out, restoreMaterial}) {
  const materials = [], screenshots = [], marker = String(Date.now());
  let course;
  const close = async () => { if (await page.locator('#toolsDialog').evaluate(el => el.open)) await page.locator('#toolsDialog [data-close-tool]').click(); };
  const open = async (scoped = false) => {
    await close(); await page.locator('#readerOptions > summary').click(); await page.locator('#moreTools').click();
    await page.locator('[data-action="courses"]').click();
    if (scoped) { await page.locator(`[data-course="${course.id}"]`).click(); await page.locator('[data-action="course-relations"]').click(); }
    else await page.locator('[data-action="library-relations"]').click();
    await page.locator('[data-cited-relation-form]').waitFor();
  };
  const generate = async () => {
    const reply = page.waitForResponse(r => new URL(r.url()).pathname === '/api/concept-relations');
    await page.locator('[data-cited-relation-form] button').click();
    const response = await reply; assert.equal(response.status(),200);
    await page.locator('[data-cited-relation-export]').waitFor(); return response.json();
  };
  try {
    for (const [i,text] of ['Gradient descent requires gradients.','\nGradient descent requires gradients.\n','Gradient descent does not require gradients.'].entries()) {
      materials.push((await api('/api/library/materials/import',{method:'POST',multipart:{file:{name:`relation-${marker}-${i}.md`,mimeType:'text/markdown',buffer:Buffer.from(text)}}})).material);
    }
    course=(await api('/api/courses',{method:'POST',data:{title:`Cited relations ${marker}`,sources:materials.map(item=>({kind:'material',id:item.material_id}))}})).course;
    const originals = await Promise.all(materials.map(item => api(`/api/library/materials/${item.material_id}/content`)));
    await page.goto(base); await page.locator(`#notes [data-id="${restoreMaterial.material_id}"]`).click();
    await open(true); const snapshot=await generate();
    assert.equal(snapshot.scope.id,course.id);
    assert.equal(snapshot.graph.edges.filter(edge=>edge.kind==='source_assertion').length,1);
    assert.equal(snapshot.graph.edges.filter(edge=>edge.kind==='inferred').length,1);
    assert.equal(await page.locator('[data-cited-relation-kind="source_assertion"]').count(),1);
    assert.equal(await page.locator('[data-cited-relation-kind="inferred"]').count(),1);
    assert.match(await page.locator('[data-cited-relation-results]').innerText(),/不证明事实或共识/);
    await page.locator('.relationship-graph > summary').click();
    assert.equal(await page.locator('.relationship-edge[stroke-dasharray=""]').count(),1);
    assert.equal(await page.locator('.relationship-edge[stroke-dasharray="2 4"]').count(),1);
    const edgePositions = await page.locator('.relationship-edge').evaluateAll(lines => lines.map(line => ['x1','y1','x2','y2'].map(key => line.getAttribute(key)).join(',')));
    assert.equal(new Set(edgePositions).size,2,'Quoted and inferred edges must not overlap');
    for (const width of [390,768,1280,1440]) {
      await page.setViewportSize({width,height:1000});
      for (const dark of [false,true]) {
        await page.evaluate(dark=>document.body.classList.toggle('dark',dark),dark);
        await page.locator('[data-cited-relation-form]').scrollIntoViewIfNeeded();
        const geometry=await page.locator('#toolsDialog').evaluate(el=>({left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right,width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth+1}));
        assert(!geometry.overflow&&geometry.left>=-1&&geometry.right<=geometry.width+1,JSON.stringify(geometry));
        const name=`cited-relations-${width}-${dark?'dark':'light'}.png`; await page.screenshot({path:path.join(out,name),fullPage:false});screenshots.push(name);
        await page.locator(".relationship-graph svg").scrollIntoViewIfNeeded();
        const graphName=`cited-relations-graph-${width}-${dark?'dark':'light'}.png`;
        await page.screenshot({path:path.join(out,graphName),fullPage:false});screenshots.push(graphName);
      }
    }
    await page.setViewportSize({width:1440,height:1000}); await page.evaluate(()=>document.body.classList.remove('dark'));
    const download=page.waitForEvent('download'); await page.locator('[data-cited-relation-export]').click();
    const file=path.join(out,'cited-relations.json');await(await download).saveAs(file);assert.deepEqual(JSON.parse(fs.readFileSync(file,'utf8')),snapshot);
    await page.locator('#relation-source_id').fill(materials[0].material_id); const selected=await generate();
    assert.equal(selected.schema_version,2);assert.equal(await page.locator('[data-cited-relation-kind]').count(),2);
    assert(selected.graph.edges.every(edge=>edge.citations.some(citation=>citation.source.id===materials[0].material_id)));
    assert(selected.graph.edges.every(edge=>new Set(edge.citations.map(citation=>citation.source_identity)).size>=2));
    await page.locator('[data-cited-relation-kind]').first().scrollIntoViewIfNeeded();
    const selectedName='cited-relations-selected-source.png';await page.screenshot({path:path.join(out,selectedName),fullPage:false});screenshots.push(selectedName);
    await page.locator('#relation-source_id').fill('');await page.locator('#relation-start').fill('10');await generate();assert.equal(await page.locator('[data-cited-relation-kind]').count(),0);
    await page.locator('#relation-start').fill('');await generate();
    const evidenceId=await page.locator('[data-cited-relation-open]').first().getAttribute('data-cited-relation-open');
    await page.locator('[data-cited-relation-open]').first().click();await page.waitForFunction(()=>!document.querySelector('#toolsDialog').open);
    const selectedCitation=snapshot.graph.edges.flatMap(edge=>edge.citations).find(item=>item.evidence_id===evidenceId);
    assert(selectedCitation);
    await page.waitForFunction(source=>document.querySelector('#document')?.dataset.readerSource===`${source.kind}:${source.id}`,selectedCitation.source);
    assert((await page.locator('#document').innerText()).includes(selectedCitation.quote));
    await open(); await page.locator('#relation-q').fill('gradient');const whole=await generate();assert.equal(whole.scope.kind,'library');
    const fileInput=page.locator('[data-cited-relation-file]');
    const reply=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/concept-relations/preview');
    await fileInput.setInputFiles(file);assert.equal((await reply).status(),200);
    await page.getByText('文件内部一致性已核对，身份与内容真实性未验证。只读查看文件内出处，不访问或重建本机资料。',{exact:true}).waitFor();
    assert.equal(await page.locator('[data-cited-relation-open]').count(),0);
    const second=page.waitForEvent('download');await page.locator('[data-cited-relation-export]').click();const again=path.join(out,'cited-relations-reexport.json');await(await second).saveAs(again);assert.deepEqual(JSON.parse(fs.readFileSync(again,'utf8')),snapshot);
    const bad=structuredClone(snapshot);bad.graph.edges[0].truth_verified=true;
    const rejected=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/concept-relations/preview');
    await fileInput.setInputFiles({name:'tampered.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(bad))});assert.equal((await rejected).status(),409);assert.equal(await page.locator('[data-cited-relation-export]').count(),0);
    const legacy=JSON.parse(fs.readFileSync(path.join(__dirname,'../backend/tests/fixtures/cited_relations_v1_source_filter.json'),'utf8')).selected_source;
    const legacyReply=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/concept-relations/preview');
    await fileInput.setInputFiles({name:'legacy-source-filter.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(legacy))});assert.equal((await legacyReply).status(),200);
    await page.getByText('旧版文件先筛选单个来源，因此没有跨来源关系。此处保留原文件结果；需要新筛选方式时，请从本机来源重新生成。',{exact:true}).waitFor();
    assert.equal(await page.locator('[data-cited-relation-kind]').count(),0);assert.equal(await page.locator('[data-cited-relation-open]').count(),0);
    const legacyDownload=page.waitForEvent('download');await page.locator('[data-cited-relation-export]').click();
    const legacyFile=path.join(out,'cited-relations-v1-reexport.json');await(await legacyDownload).saveAs(legacyFile);assert.deepEqual(JSON.parse(fs.readFileSync(legacyFile,'utf8')),legacy);
    assert.deepEqual(await Promise.all(materials.map(item=>api(`/api/library/materials/${item.material_id}/content`))),originals);
    return {passed:true,actual_backend:true,synthetic_only:true,screenshots,checks:['course/full-library','two-source quoted vs inferred display','selected-source relations retain counterpart citations','source/time filters','canonical source opening','lossless snapshot export/import','legacy v1 source-filter roundtrip','tamper rejection','unchanged original material']};
  } finally {
    await close();await page.setViewportSize({width:1440,height:900});await page.evaluate(()=>document.body.classList.remove('dark'));
    if(course)await page.request.delete(new URL(`/api/courses/${course.id}`,base).href);
    for(const item of materials)await page.request.delete(new URL(`/api/library/materials/${item.material_id}?confirm=delete_material`,base).href);
    await page.goto(base);await page.locator(`#notes [data-id="${restoreMaterial.material_id}"]`).click();
  }
};
