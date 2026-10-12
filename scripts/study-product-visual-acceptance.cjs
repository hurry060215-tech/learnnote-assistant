/* Actual default reader/studio + isolated backend. No remote model calls. */
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const {execFileSync}=require("node:child_process");
const cases=()=>[390,768,1024,1440].flatMap(width=>[90,100,200].map(zoom=>({width,zoom,cssWidth:Math.round(width/(zoom/100)),cssHeight:Math.round(900/(zoom/100))})));
const effectCases=()=>["light","dark"].flatMap(theme=>[
  {name:"normal",motion:false,transparency:false},
  {name:"reduced-motion",motion:true,transparency:false},
  {name:"reduced-transparency",motion:false,transparency:true},
  {name:"reduced-both",motion:true,transparency:true},
].map(item=>({...item,theme})));
function assertDialogEffects(sample,item){
  assert(sample.open&&sample.modal,"The actual dialog must be open in the modal top layer");
  assert.equal(sample.forcedColors,false,"Forced colors must not mask reduced-effects regressions");
  assert.equal(sample.reducedMotion,item.motion);
  assert.equal(sample.reducedTransparency,item.transparency);
  const style=sample.backdrop,color=style.backgroundColor.match(/[\d.]+/g).map(Number),alpha=color[3]??1;
  assert.equal(style.opacity,"1","The backdrop must settle fully");
  assert.equal(style.backdropFilter,item.transparency?"none":"blur(3px)");
  if(item.transparency){
    assert.equal(alpha,1,"Reduced transparency requires an opaque backdrop");
    assert.deepEqual(color.slice(0,3),item.theme==="dark"?[37,37,37]:[245,246,243]);
  }else{
    assert.deepEqual(color.slice(0,3),[21,21,21]);
    assert(alpha>0&&alpha<1,"Normal transparency must retain its existing translucent backdrop");
  }
  const noBackdropAnimation=item.motion||item.transparency;
  assert.equal(style.animationName,noBackdropAnimation?"none":"backdrop-arrive");
  assert.equal(parseFloat(style.animationDuration),noBackdropAnimation?0:0.16);
  assert.equal(parseFloat(style.transitionDuration),0);
  assert.equal(sample.dialog.animationName,item.motion?"none":"dialog-arrive");
  assert.equal(parseFloat(sample.dialog.animationDuration),item.motion?0:0.12);
}
async function dialogEffects({page,cdp,openStudio,capture}){
  const results=[];
  for(const item of effectCases()){
    await cdp.send("Emulation.setEmulatedMedia",{features:[
      {name:"forced-colors",value:"none"},
      {name:"prefers-reduced-motion",value:item.motion?"reduce":"no-preference"},
      {name:"prefers-reduced-transparency",value:item.transparency?"reduce":"no-preference"},
    ]});
    await page.evaluate(theme=>document.body.classList.toggle("dark",theme==="dark"),item.theme);
    await openStudio();
    for(const selector of ["#toolsDialog","#createDialog"]){
      if(selector==="#createDialog")await page.locator("#newNote").click();
      await page.locator(selector).waitFor({state:"visible"});
      await page.waitForFunction(selector=>getComputedStyle(document.querySelector(selector),"::backdrop").opacity==="1",selector);
      const sample=await page.locator(selector).evaluate(dialog=>{
        const properties=style=>Object.fromEntries(["backgroundColor","backdropFilter","opacity","animationName","animationDuration","transitionDuration"].map(key=>[key,style[key]]));
        return {open:dialog.open,modal:dialog.matches(":modal"),forcedColors:matchMedia("(forced-colors:active)").matches,
          reducedMotion:matchMedia("(prefers-reduced-motion:reduce)").matches,reducedTransparency:matchMedia("(prefers-reduced-transparency:reduce)").matches,
          backdrop:properties(getComputedStyle(dialog,"::backdrop")),dialog:properties(getComputedStyle(dialog))};
      });
      assertDialogEffects(sample,item);
      await capture(`backdrop-${item.theme}-${item.name}-${selector.slice(1)}`,selector);
      results.push({...item,selector,...sample});
      await page.locator(`${selector} ${selector==="#toolsDialog"?"[data-close-tool]":"[data-close]"}`).click();
    }
  }
  await cdp.send("Emulation.setEmulatedMedia",{features:[{name:"forced-colors",value:"none"},{name:"prefers-reduced-motion",value:"reduce"},{name:"prefers-reduced-transparency",value:"no-preference"}]});
  await page.evaluate(()=>document.body.classList.remove("dark"));await openStudio();
  return results;
}
async function geometry(page,selector){return page.locator(selector).evaluate(root=>{
  const width=document.documentElement.clientWidth,b=root.getBoundingClientRect();
  const controls=[...root.querySelectorAll("button,input,select,textarea,summary")].filter(el=>!el.hidden&&el.getClientRects().length);
  const clipped=controls.filter(el=>{const r=el.getBoundingClientRect();return r.left < -1 || r.right > width+1;}).map(el=>el.id||el.textContent.slice(0,30));
  const rgb=value=>{const parts=value.match(/[\d.]+/g)?.map(Number)||[0,0,0];return parts;};
  let node=root,bg;
  while(node){const value=rgb(getComputedStyle(node).backgroundColor);if(value.length<4||value[3]>.99){bg=value;break;}node=node.parentElement;}
  bg ||= [255,255,255];const fg=rgb(getComputedStyle(root).color);
  const luminance=channels=>channels.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
  const a=luminance(fg),c=luminance(bg);
  const overflowing=document.documentElement.scrollWidth>width+1?[...document.querySelectorAll("body *")].filter(el=>el.getClientRects().length&&el.checkVisibility?.()!==false&&el.getBoundingClientRect().right>width+1).slice(0,24).map(el=>({tag:el.tagName,id:el.id,className:String(el.className),left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right,width:el.getBoundingClientRect().width})):[];
  return {overflowing,viewport:width,scrollWidth:document.documentElement.scrollWidth,left:b.left,right:b.right,clipped,contrast:(Math.max(a,c)+.05)/(Math.min(a,c)+.05),backdrop:getComputedStyle(root).backdropFilter};
});}
async function main(){
  const {chromium}=require("playwright"),base=process.argv[2]||"http://127.0.0.1:8765",out=path.resolve(process.argv[3]||"build/study-product-ui");fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({channel:"msedge",headless:true}),context=await browser.newContext({viewport:{width:1440,height:900},timezoneId:"Asia/Shanghai",reducedMotion:"reduce"});
  const page=await context.newPage(),cdp=await context.newCDPSession(page),errors=[];page.setDefaultTimeout(15000);page.on("pageerror",e=>errors.push(e.message));page.on("dialog",dialog=>dialog.accept());
  const report={schema_version:1,source_sha:execFileSync("git",["rev-parse","HEAD"],{encoding:"utf8"}).trim(),browser:browser.version(),surface:"actual default / reader and study tools",backend:"real isolated CI service, synthetic local Markdown and evidence cards",zoom_method:"effective CSS viewport and CDP deviceScaleFactor; not native toolbar zoom",native_webview_tested:false,cases:[]};
  const api=async(route,options)=>{const response=await page.request.fetch(new URL(route,base).href,options);assert(response.ok(),`${route}: ${response.status()} ${await response.text()}`);return response.json();};
  let material,course,cards=[];
  try {
    const marker=String(Date.now());
    const body="# Study visual acceptance "+marker+"\n\nLearning rate controls the parameter update step and influences convergence speed.\n\n"+Array.from({length:60},(_,i)=>`## Section ${i+1}\n\n学习原文第 ${i+1} 段。The original reading surface stays opaque and evidence remains traceable.`).join("\n\n");
    material=(await api("/api/library/materials/import",{method:"POST",multipart:{file:{name:`study-visual-${marker}.md`,mimeType:"text/markdown",buffer:Buffer.from(body)}}})).material;
    const anchors=(await api(`/api/library/materials/${material.material_id}/anchors`)).anchors;const evidence=anchors.find(item=>item.text.includes("Learning rate controls"));assert(evidence);
    course=(await api("/api/courses",{method:"POST",data:{title:`Visual course ${marker}`,sources:[{kind:"material",id:material.material_id}]}})).course;
    cards=(await api("/api/study/cards",{method:"POST",data:{cards:[{front:`Question ${marker}`,back:"The parameter update step.",source_evidence_ids:[evidence.evidence_id]},{front:`Mistake ${marker}`,back:"Check the original explanation.",source_evidence_ids:[evidence.evidence_id]}]}})).cards;
    await api(`/api/study/cards/${cards[1].card_id}/review`,{method:"POST",data:{rating:1,idempotency_key:`visual-${marker}`}});
    await api("/api/study/plan",{method:"PUT",data:{title:"Synthetic local review",daily_target:3,paused:false,timezone:"Asia/Shanghai"}});
    await page.goto(base);await page.locator(`[data-id="${material.material_id}"][data-kind="material"]`).first().click();await page.locator("#document").getByText(/Learning rate controls/).waitFor();
    await page.locator("#moreTools").click();
    const rebuildReply=page.waitForResponse(response=>response.request().method()==="POST"&&response.url().endsWith(`/api/library/materials/${material.material_id}/rebuild`));
    await page.locator('[data-action="rebuild-material"]').click();assert.equal((await rebuildReply).status(),200);
    await page.getByText(/已从本机原文件恢复 .* 条出处；现有引用 ID 保留。/).waitFor();
    const repaired=(await api(`/api/library/materials/${material.material_id}`)).material;
    assert.deepEqual(repaired.evidence_ids,material.evidence_ids);assert(repaired.metadata.reindexed_at);
    assert.deepEqual((await api(`/api/library/materials/${material.material_id}/anchors`)).anchors.map(item=>item.evidence_id),anchors.map(item=>item.evidence_id));
    report.material_rebuild={same_ids:true,anchor_count:repaired.anchor_count,reader_reopened:true};
    report.material_encoding=await require("./reader-encoding-acceptance.cjs")({page,api,base,out,restoreMaterial:material});
    const openStudio=async()=>{
      if(await page.locator("#toolsDialog").evaluate(el=>el.open))await page.locator("[data-close-tool]").click();
      await page.locator("#moreTools").click();await page.locator('[data-action="add-to-course"]').click();await page.locator(`[data-add-course="${course.id}"]`).click();await page.locator('[data-action="course-review"]').click();await page.locator("#studyVideoFilter").waitFor();
    };
    const capture=async(name,selector)=>{const g=await geometry(page,selector);await page.screenshot({path:path.join(out,name+".png"),fullPage:true});assert(g.scrollWidth<=g.viewport+1,`${name} page overflow: ${JSON.stringify(g)}`);assert(g.left>=-1&&g.right<=g.viewport+1,`${name} clipped surface`);assert.deepEqual(g.clipped,[],`${name} clipped controls`);assert(g.contrast>=4.5,`${name} contrast ${g.contrast}`);return g;};
    report.objective_cloze=await require("./study-quiz-acceptance.cjs")({page,api,openStudio,evidence,cards,capture});
    report.concept_groups=await require("./course-concepts-acceptance.cjs")({page,api,base,out,restoreMaterial:material});
    for(const item of cases()){
      await page.setViewportSize({width:item.cssWidth,height:item.cssHeight});await cdp.send("Emulation.setDeviceMetricsOverride",{width:item.cssWidth,height:item.cssHeight,deviceScaleFactor:item.zoom/100,mobile:false});
      for(const theme of ["light","dark"]){
        await page.evaluate(theme=>document.body.classList.toggle("dark",theme==="dark"),theme);
        if(await page.locator("#toolsDialog").evaluate(el=>el.open))await page.locator("[data-close-tool]").click();
        const reader=await capture(`reader-${item.width}-${item.zoom}-${theme}`,"#document");assert.equal(reader.backdrop,"none","Reading text must never be blurred");
        await openStudio();assert.equal(await page.locator(".study-activity-grid li").count(),14);
        const studio=await capture(`studio-${item.width}-${item.zoom}-${theme}`,"#toolsDialog");report.cases.push({...item,theme,reader,studio});
      }
    }
    await page.setViewportSize({width:1440,height:900});await cdp.send("Emulation.clearDeviceMetricsOverride");await page.evaluate(()=>document.body.classList.remove("dark"));await openStudio();
    await page.locator('[data-action="start-review"]').focus();await page.keyboard.press("Enter");await page.locator("#reviewReflection").waitFor();
    await page.locator("#reviewReflection").fill("My own explanation stays local.");await page.locator("#recordReflection").focus();await page.keyboard.press("Enter");await page.locator("#answer").waitFor({state:"visible"});
    await page.locator(`#reviewSources [data-evidence="${evidence.evidence_id}"]`).click();
    const sourceTarget=page.locator(`#sourceContent [data-evidence-id="${evidence.evidence_id}"]`);
    await sourceTarget.waitFor({state:"visible"});assert.match(await sourceTarget.innerText(),/Learning rate controls/);
    assert.match(await page.locator("#sourceContent").innerText(),/学习原文第 60 段/);
    await page.locator("#closeSource").click();await openStudio();await page.locator('[data-action="start-review"]').click();await page.locator("#skipReflection").click();
    report.document_source={exact_evidence_id:true,complete_original_retained:true};
    await page.locator("#editReviewCard").click();await page.locator("#reviewCardFront").fill(`Edited ${marker}`);await page.locator("#reviewCardBack").fill("My original correction 保持原文");await page.locator("#reviewCardForm button").click();await page.locator("#reviewContent h3").getByText(`Edited ${marker}`,{exact:true}).waitFor();
    const edited=(await api("/api/study/cards?limit=500")).cards.find(item=>item.front===`Edited ${marker}`);assert(edited);assert.deepEqual(edited.source_evidence_ids,[evidence.evidence_id]);
    await page.locator("#skipReflection").click();const deletion=page.waitForResponse(response=>response.request().method()==="DELETE"&&response.url().includes(`/api/study/cards/${edited.card_id}`));await page.locator("#deleteReviewCard").click();assert.equal((await deletion).status(),200);assert(!(await api("/api/study/cards?limit=500")).cards.some(item=>item.card_id===edited.card_id));
    await page.locator("#reviewDialog [data-close]").click();await openStudio();await page.getByText("调整每日目标与时区",{exact:true}).click();await page.locator("#studyPaused").check();await page.locator("#planForm button").click();await page.waitForFunction(()=>document.querySelector("#toolStatus").textContent.includes("保存"));await openStudio();await page.locator('[data-action="resume-study"]').waitFor();assert.equal((await api(`/api/study/due?course_id=${course.id}`)).cards.length,0);await page.locator('[data-action="resume-study"]').click();await page.locator('[data-action="start-review"]').waitFor();
    report.dialog_effects=await dialogEffects({page,cdp,openStudio,capture});
    await cdp.send("Emulation.setEmulatedMedia",{features:[{name:"forced-colors",value:"active"},{name:"prefers-reduced-motion",value:"reduce"},{name:"prefers-reduced-transparency",value:"reduce"}]});
    report.accessibility=await page.evaluate(()=>({forcedColors:matchMedia("(forced-colors:active)").matches,reducedMotion:matchMedia("(prefers-reduced-motion:reduce)").matches,reducedTransparency:matchMedia("(prefers-reduced-transparency:reduce)").matches}));assert(report.accessibility.forcedColors&&report.accessibility.reducedMotion&&report.accessibility.reducedTransparency);await capture("studio-forced-colors-reduced-effects","#toolsDialog");
    assert.deepEqual(errors,[]);report.page_errors=errors;report.passed=true;fs.writeFileSync(path.join(out,"report.json"),JSON.stringify(report,null,2));console.log(JSON.stringify({passed:true,cases:report.cases.length,dialog_effect_cases:report.dialog_effects.length,keyboard:"reveal/edit/delete/pause/resume",out}));
  } finally {
    for(const card of cards)await page.request.delete(new URL(`/api/study/cards/${card.card_id}?confirm=delete_card`,base).href).catch(()=>{});
    if(course)await page.request.delete(new URL(`/api/courses/${course.id}`,base).href).catch(()=>{});
    if(material)await page.request.delete(new URL(`/api/library/materials/${material.material_id}?confirm=delete_material`,base).href).catch(()=>{});
    await browser.close();
  }
}
if(process.argv.includes("--self-test")){
  assert.equal(cases().length,12);assert(cases().some(item=>item.width===1024&&item.zoom===200));
  assert.equal(effectCases().length,8);
  for(const item of effectCases()){
    const sample={open:true,modal:true,forcedColors:false,reducedMotion:item.motion,reducedTransparency:item.transparency,
      backdrop:{backgroundColor:item.transparency?(item.theme==="dark"?"rgb(37, 37, 37)":"rgb(245, 246, 243)"):"rgba(21, 21, 21, 0.333)",backdropFilter:item.transparency?"none":"blur(3px)",opacity:"1",animationName:item.motion||item.transparency?"none":"backdrop-arrive",animationDuration:item.motion||item.transparency?"0s":"0.16s",transitionDuration:"0s"},
      dialog:{animationName:item.motion?"none":"dialog-arrive",animationDuration:item.motion?"0s":"0.12s"}};
    assertDialogEffects(sample,item);
    assert.throws(()=>assertDialogEffects({...sample,forcedColors:true},item));
    assert.throws(()=>assertDialogEffects({...sample,open:false},item));
    assert.throws(()=>assertDialogEffects({...sample,backdrop:{...sample.backdrop,backdropFilter:item.transparency?"blur(3px)":"none"}},item));
    assert.throws(()=>assertDialogEffects({...sample,backdrop:{...sample.backdrop,animationName:item.motion||item.transparency?"backdrop-arrive":"none"}},item));
    assert.throws(()=>assertDialogEffects({...sample,backdrop:{...sample.backdrop,backgroundColor:item.transparency?"rgba(21, 21, 21, 0.333)":"rgb(21, 21, 21)"}},item));
  }
  console.log("Default reader/studio matrix and 8 dialog-effects assertion cases passed; no browser launched");
}else main().catch(error=>{console.error(error);process.exitCode=1;});
