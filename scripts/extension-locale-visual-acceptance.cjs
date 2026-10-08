/* Real Edge rendering. Chrome APIs and local-service replies are explicit fixtures. */
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), http = require("node:http");
const {execFileSync} = require("node:child_process");
const ROOT = path.resolve(__dirname,"..");
const matrix = () => ["zh-CN","en-US"].flatMap(locale => [390,768,1440].flatMap(width => [90,100,200].map(zoom => ({locale,width,zoom,cssWidth:Math.round(width/(zoom/100)),cssHeight:Math.round(900/(zoom/100))}))));
function asset(url) {
  let name; try {name=decodeURIComponent(new URL(url,"http://localhost").pathname);} catch{return null;}
  if(!name.startsWith("/extension/"))return null;
  const root=path.join(ROOT,"extension"), file=path.resolve(root,name.slice(11));
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile())return null;
  return fs.realpathSync(file).startsWith(root+path.sep)?file:null;
}
const FIXTURE={title:"合成课程 Synthetic lesson：保持用户原文 🧭",note:"# 用户笔记保持原文\n\n原文结论 {model} 00:05",instruction:"保留用户原文与代码 {model}，不要自动翻译。",question:"这段视频说明了什么？ {model}",subtitle:"原文字幕：不要翻译这段用户内容。"};
function installFixtures({locale,catalog,fixture}) {
  const originalFetch=globalThis.fetch.bind(globalThis);let release;
  const healthGate=new Promise(resolve=>{release=resolve;});
  const site="https://www.bilibili.com/video/BV1SYNTHETIC?p=1";
  const cues=Array.from({length:12},(_,i)=>({start:i*10,end:i*10+10,text:fixture.subtitle+" "+(i+1)}));
  const page={page_url:site,title:fixture.title,active_video:{src:"https://example.com/synthetic.mp4",duration:120,current_time:45,paused:false,has_audio:true},browser_subtitles:cues,subtitle_probe:{status:"ready",elapsed_ms:400},chapters:[{title:"原文章节一",start:0,end:60},{title:"原文章节二",start:60,end:120}]};
  const control=globalThis.__localeFixture={health:"loading",startError:"",sent:[],unexpected:[],storage:{processingMode:"study"},context:{tab:{id:7,url:site,title:fixture.title},page,resources:[]},connect(){this.health="connected";release();}};
  const json=value=>new Response(JSON.stringify(value),{status:200,headers:{"Content-Type":"application/json"}});
  globalThis.fetch=async(input,options={})=>{
    const url=new URL(String(input),location.href);
    if(url.origin===location.origin)return originalFetch(input,options);
    if(url.origin!=="http://127.0.0.1:8765"){control.unexpected.push(url.origin+url.pathname);throw Error("Unexpected external request in synthetic fixture");}
    if(url.pathname==="/health"){
      if(control.health==="loading")await healthGate;
      if(control.health==="offline")throw TypeError("Failed to fetch");
      return json({service:"learnnote",app_version:"0.2.14",backend_version:"0.2.14",protocol_version:control.health==="incompatible"?999:1,llm_model_configured:true,default_llm_model:"Synthetic-long-model-name-for-layout-acceptance",default_llm_supports_vision:true});
    }
    if(url.pathname==="/api/preferences")return json({task_options:{note_profile_prompt:fixture.instruction}});
    if(url.pathname==="/api/pairing/issue")return json({token:"synthetic-fixture-only",expires_at:Date.now()/1000+300});
    if(url.pathname.endsWith("/note"))return new Response(fixture.note);
    if(url.pathname.endsWith("/transcript"))return json({segments:cues});
    if(url.pathname.endsWith("/qa"))return json({answer:"用户回答保持原文",source:"local",citations:[]});
    if(url.pathname.includes("/api/tasks/"))return json({task:{id:"locale-fixture",status:"success",note_path:"synthetic-note",options:{content_mode:"text"}}});
    return json({configured:true,model:{model:"synthetic"},report:{ready:true,ok:true}});
  };
  const noop=()=>{};
  globalThis.chrome={
    i18n:{getUILanguage:()=>locale,getMessage:key=>catalog[key]?.message||""},
    permissions:{contains:async()=>true,getAll:async()=>({origins:["https://www.bilibili.com/*"]}),request:async()=>true,remove:async()=>true,onRemoved:{addListener:noop}},
    storage:{local:{get:async defaults=>({...((defaults && !Array.isArray(defaults))?defaults:{}),...control.storage}),set:async values=>Object.assign(control.storage,values)}},
    tabs:{query:async query=>query?.url?[]:[control.context.tab],get:async()=>control.context.tab,create:async()=>({id:8}),update:async()=>({id:8}),onActivated:{addListener:noop}},
    runtime:{onMessage:{addListener:noop},sendMessage:async message=>{
      control.sent.push(message);
      if(message.type==="get-current-context")return control.context;
      if(message.type==="start-current-task")return control.startError?{error:control.startError}:{task_id:"locale-fixture",accepted:true};
      return {ok:true,report:{ready:true,ok:true}};
    }}
  };
}
async function geometry(page) {
  return page.evaluate(()=>{
    const width=document.documentElement.clientWidth;
    const checked=[...document.querySelectorAll("button,input,select,textarea,summary,.connection-card,.handoff-card,.quick-result-card")].filter(el=>el.getClientRects().length&&!el.hidden);
    const overflow=checked.filter(el=>{const b=el.getBoundingClientRect();return b.left < -1 || b.right > width+1;}).map(el=>({id:el.id,tag:el.tagName,rect:el.getBoundingClientRect().toJSON()}));
    return {width,scrollWidth:document.documentElement.scrollWidth,bodyScrollWidth:document.body.scrollWidth,overflow,lang:document.documentElement.lang};
  });
}
async function run() {
  const {chromium}=require("playwright"),out=path.resolve(process.argv[2]||"build/extension-locales");fs.mkdirSync(out,{recursive:true});
  const server=http.createServer((req,res)=>{const file=asset(req.url);if(!file){res.writeHead(404);res.end();return;}res.setHeader("Content-Type",file.endsWith(".css")?"text/css":file.endsWith(".js")?"text/javascript":file.endsWith(".json")?"application/json":file.endsWith(".png")?"image/png":"text/html");fs.createReadStream(file).pipe(res);});
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  const browser=await chromium.launch({channel:"msedge",headless:true});
  const report={schema_version:1,source_sha:execFileSync("git",["rev-parse","HEAD"],{cwd:ROOT,encoding:"utf8"}).trim(),browser:browser.version(),zoom_method:"effective CSS viewport plus deviceScaleFactor; not native toolbar zoom",chrome_apis:"synthetic runtime/storage/permissions/tabs/i18n",backend:"synthetic local-service replies; no model or website access",native_installation_or_permission_prompts_tested:false,cases:[],store_candidates:[]};
  try {
    for(const item of matrix()){
      const context=await browser.newContext({viewport:{width:item.cssWidth,height:item.cssHeight},deviceScaleFactor:item.zoom/100,locale:item.locale,reducedMotion:"reduce"});
      const page=await context.newPage();page.setDefaultTimeout(12000);const errors=[];page.on("pageerror",e=>errors.push(e.message));
      const catalog=JSON.parse(fs.readFileSync(path.join(ROOT,"extension","_locales",item.locale.startsWith("en")?"en":"zh_CN","messages.json"),"utf8"));
      await page.addInitScript(installFixtures,{locale:item.locale,catalog,fixture:FIXTURE});
      const prefix=`${item.locale}-${item.width}-${item.zoom}`;
      const capture=async state=>{const g=await geometry(page);assert.equal(g.scrollWidth<=g.width+1,true,`${prefix}/${state} page overflow`);assert.equal(g.bodyScrollWidth<=g.width+1,true,`${prefix}/${state} hidden body overflow`);assert.deepEqual(g.overflow,[],`${prefix}/${state} clipped controls`);await page.screenshot({path:path.join(out,`${prefix}-${state}.png`),fullPage:true});return g;};
      await page.goto(`http://127.0.0.1:${server.address().port}/extension/sidepanel.html`,{waitUntil:"domcontentloaded"});
      await page.locator("#sourcePreviewCard").waitFor({state:"visible"});await capture("loading");
      await page.evaluate(()=>__localeFixture.connect());await page.waitForFunction(()=>__learnnoteSidepanel.getState().clientConnected);
      assert.equal(await page.locator("#videoTitle").innerText(),FIXTURE.title);
      assert.equal(await page.locator("html").getAttribute("lang"),item.locale.startsWith("en")?"en":"zh-CN");
      await page.locator("#learningRangeOptions > summary").click();await page.locator("#learningRangeMode").selectOption("chapter");
      await page.waitForFunction(()=>document.querySelector("#learningRangeStart").value==="0"&&document.querySelector("#learningRangeEnd").value==="60");
      await page.locator("#learningRangeMode").selectOption("whole");
      await page.locator("#sourcePreviewCard > summary").click();
      assert((await page.locator("#sourcePreviewContent").innerText()).includes(FIXTURE.subtitle));
      await page.locator("#extensionOptions").evaluate(el=>el.open=true);await page.locator("#extensionPrompt").fill(FIXTURE.instruction);assert.equal(await page.locator("#extensionPrompt").inputValue(),FIXTURE.instruction);
      const connected=await capture("connected");
      await page.locator("#sendButton").focus();assert.equal(await page.evaluate(()=>document.activeElement.id),"sendButton");await page.keyboard.press("Tab");assert(await page.evaluate(()=>document.activeElement.tagName!=="BODY"));
      await page.evaluate(()=>__localeFixture.startError="当前站点权限已撤销，本次任务未创建。");await page.locator("#sendButton").click();
      await page.waitForFunction(()=>document.querySelector("#handoffStatus").textContent.length>0&&!__learnnoteSidepanel.getState().sending);
      if(item.locale.startsWith("en"))assert(!/[\u4e00-\u9fff]/.test(await page.locator("#handoffStatus").innerText()),"Known error must be localized");
      await capture("error");await page.evaluate(()=>__localeFixture.startError="");await page.locator("#sendButton").click();
      await page.locator("#quickSummaryPanel").getByText("用户笔记保持原文",{exact:false}).waitFor();
      assert((await page.locator("#quickSummaryPanel").innerText()).includes("{model}"));
      await page.locator('[data-quick-tab="ask"]').click();await page.locator("#quickAskQuestion").fill(FIXTURE.question);assert.equal(await page.locator("#quickAskQuestion").inputValue(),FIXTURE.question);await page.locator('[data-quick-tab="summary"]').click();
      await capture("results");
      if(item.width===390&&item.zoom===100){for(const state of ["offline","incompatible"]){await page.evaluate(state=>{__localeFixture.health=state;},state);await page.evaluate(()=>__learnnoteSidepanel.checkClient());await capture(state);}}
      const unexpected=await page.evaluate(()=>__localeFixture.unexpected);assert.deepEqual(unexpected,[]);assert.deepEqual(errors,[]);
      report.cases.push({...item,geometry:connected,page_errors:errors,external_requests:unexpected});
      if(item.width===1440&&item.zoom===100){await page.setViewportSize({width:1280,height:800});await page.evaluate(()=>{__localeFixture.health="connected";});await page.evaluate(()=>__learnnoteSidepanel.checkClient());await page.evaluate(()=>{for(const id of ["sourcePreviewCard","learningRangeOptions","extensionOptions"])document.getElementById(id).open=false;});for(const state of ["summary","transcript"]){await page.locator(`[data-quick-tab="${state}"]`).click();await page.locator("#quickResultCard").scrollIntoViewIfNeeded();const filename=`store-${item.locale}-${state}-1280x800.png`;await page.screenshot({path:path.join(out,filename)});report.store_candidates.push(filename);}}
      await context.close();
    }
    report.passed=true;fs.writeFileSync(path.join(out,"report.json"),JSON.stringify(report,null,2));console.log(JSON.stringify({passed:true,cases:report.cases.length,store_candidates:report.store_candidates.length,out}));
  } finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
}
if(process.argv.includes("--self-test")){
  assert.equal(matrix().length,18);assert.equal(asset("/extension/../../backend/app/main.py"),null);assert.equal(asset("/extension/%2e%2e/backend/app/main.py"),null);assert(asset("/extension/sidepanel.html"));console.log("Locale visual matrix/path self-test passed; no browser launched");
}else run().catch(error=>{console.error(error);process.exitCode=1;});
