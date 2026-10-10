// Actual Edge + local API operations; only the model's proposed tool call is mocked.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const base=process.argv[2]||'http://127.0.0.1:8765', out=process.argv[3]||'build/assistant-operations-ui';
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  const errors=[];p.on('pageerror',e=>errors.push(e.message));
  const fixture='# Agent synthetic source\n\nOriginal paragraph.\n\nSynthetic source only.\n';
  let materialId, proposed=0, executions=0;
  p.on('request',r=>{if(r.method()==='POST'&&/\/api\/assistant\/operations\/[^/]+\/execute$/.test(new URL(r.url()).pathname))executions++;});
  const dialog=()=>p.locator('#assistantOperationsDialog');
  const card=()=>dialog().locator('[data-agent-card]');
  async function local(tool,fields={}){
    await dialog().locator('[name=tool]').selectOption(tool);
    for(const [name,value] of Object.entries(fields)){
      const field=dialog().locator(`[name=${name}]`);
      if(await field.evaluate(el=>el.tagName==='SELECT'))await field.selectOption(value);else await field.fill(value);
    }
    await dialog().locator('[data-agent-local] button[type=submit]').click();
    await card().getByRole('button',{name:'执行此操作',exact:true}).waitFor();
  }
  async function apply(){await card().locator('[data-agent-apply]').click();await p.waitForFunction(()=>document.querySelector('[data-agent-card] h3').textContent.includes('已完成'));await p.waitForFunction(()=>!document.querySelector('[data-agent-plan]').disabled);}
  async function edition(){return (await p.request.get(`${base}/api/tasks/editions/material/${materialId}`)).json();}
  try{
    const imported=await p.request.post(base+'/api/library/materials/import',{multipart:{file:{name:'agent-synthetic.md',mimeType:'text/markdown',buffer:Buffer.from(fixture)}}});
    assert(imported.ok(),await imported.text());materialId=(await imported.json()).material.material_id;
    await p.goto(base);await p.locator(`#notes [data-id="${materialId}"]`).click();
    await p.waitForFunction(()=>document.querySelector('#document').textContent.includes('Original paragraph.'));
    await p.locator('#aiAssistant').click();await p.locator('#assistantOperations').click();
    await local('read_note');await apply();assert.match(await card().innerText(),/Original paragraph/);
    await local('edit_note',{mode:'replace',old_text:'Original paragraph.',text:'Edited by the native tool.'});
    assert.match(await card().locator('pre').innerText(),/-Original paragraph/);
    assert.match((await edition()).text,/Original paragraph/);await apply();
    assert.match((await edition()).text,/Edited by the native tool/);
    await card().locator('[data-agent-undo]').click();
    await p.waitForFunction(()=>document.querySelector('#document').textContent.includes('Original paragraph.'));
    assert.equal((await edition()).text,fixture);assert.equal(await card().locator('[data-agent-undo]').count(),0);
    for(const format of ['markdown','html','docx','pdf']){
      await local('export_note',{format});await apply();
      const href=await card().getByRole('link',{name:'下载已生成文件'}).getAttribute('href');
      const download=await p.request.get(base+href);assert(download.ok());
      const bytes=await download.body();assert(bytes.length>20);
      if(format==='pdf')assert.equal(bytes.subarray(0,4).toString(),'%PDF');
      if(format==='docx')assert.equal(bytes.subarray(0,2).toString(),'PK');
      if(format==='markdown'||format==='html')assert.match(bytes.toString(),/Original paragraph/);
    }
    const beforeReading=await p.evaluate(()=>window.LearnNoteReadingSettings.read());
    await local('update_reading',{theme:beforeReading.settings.theme==='dark'?'light':'dark',size:'20'});await apply();
    assert.equal((await p.evaluate(()=>window.LearnNoteReadingSettings.read())).settings.size,20);
    await p.screenshot({path:out+'/desktop-operations.png'});
    await card().locator('[data-agent-undo]').click();await p.waitForFunction(()=>!document.querySelector('[data-agent-undo]'));
    assert.deepEqual((await p.evaluate(()=>window.LearnNoteReadingSettings.read())).settings,beforeReading.settings);
    // Exercise proposal -> preview -> genuine API commit. No real model/key/network.
    await p.route('**/api/assistant/operations/plan',async route=>{
      proposed++;const request=route.request().postDataJSON();assert.equal(request.share_source,false);
      await route.fulfill({json:{state:'proposed',tool:'edit_note',arguments:{mode:'append',text:'Structured proposal applied.',old_text:''},source:request.source,shared_characters:0,executed:false}});
    });
    await dialog().locator('details').first().locator('summary').click();
    await dialog().locator('[data-agent-question]').fill('Append the synthetic sentence.');
    const beforeExecution=executions;
    await dialog().locator('[data-agent-plan]').click();await card().locator('[data-agent-apply]').waitFor();
    assert.equal(executions,beforeExecution);assert.doesNotMatch((await edition()).text,/Structured proposal/);
    await apply();assert.match((await edition()).text,/Structured proposal applied/);assert.equal(proposed,1);
    await local('edit_note',{mode:'append',text:'Must be cancelled.'});
    await card().locator('[data-agent-cancel]').click();await p.waitForFunction(()=>document.querySelector('[data-agent-card] h3').textContent.includes('已取消'));
    assert.doesNotMatch((await edition()).text,/Must be cancelled/);
    await p.setViewportSize({width:390,height:844});await p.screenshot({path:out+'/mobile-operations.png'});
    assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    const original=await p.request.get(`${base}/api/library/materials/${materialId}/source`);assert(original.ok());assert.equal((await original.body()).toString(),fixture);
    // Delete only the fixture created by this script; its operation copies must go too.
    const records=(await (await p.request.get(base+'/api/assistant/operations')).json()).operations.filter(v=>v.source?.id===materialId);
    assert(records.length>=8);
    assert((await p.request.delete(`${base}/api/library/materials/${materialId}?confirm=delete_material`)).ok());
    for(const record of records)assert.equal((await p.request.get(`${base}/api/assistant/operations/${record.id}`)).status(),404);
    assert.deepEqual(errors,[]);
    fs.writeFileSync(out+'/result.json',JSON.stringify({ok:true,actualRead:true,actualEditAndUndo:true,actualExports:4,actualAppearanceAndUndo:true,structuredProposalWithRealExecution:true,modelResponseMocked:true,cancelBeforeCommit:true,sourceDeletionRemovesCopies:true,originalUnchangedBeforeDeletion:true,errors},null,2));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
