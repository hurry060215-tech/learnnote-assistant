// Deterministic product tests. All model calls and browser-extension APIs are mocked.
const {chromium}=require('playwright');
const fs=require('node:fs'), path=require('node:path'), os=require('node:os'), assert=require('node:assert/strict');
(async()=>{
  const base=process.argv[2]||'http://127.0.0.1:18956';
  const out=process.argv[3]||path.join(os.tmpdir(),'learnnote-core-output');fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
    page.setDefaultTimeout(8000);
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    let prepares=0;
    await page.route('**/api/local-models/*/prepare',r=>{prepares++;return r.fulfill({json:{status:'downloading',message:'下载请求已接收'}});});
    await page.route('**/api/model/usage',r=>r.fulfill({json:{totals:{requests:2,measured_requests:1,input_tokens:1200,output_tokens:300,total_tokens:1500},daily:[{day:'2026-09-09',total_tokens:1500}],models:[{model:'验收模型',host:'example.test',total_tokens:1500}],recent:[]}}));
    await page.goto(base);await page.locator('#profile').click();
    await page.locator('.profile-stats').getByText('1,500',{exact:true}).waitFor();
    assert.equal(await page.locator('.profile-stats').evaluate(el=>getComputedStyle(el).display),'grid');
    await page.screenshot({path:path.join(out,'profile-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    assert(await page.locator('#profileDialog').evaluate(el=>el.getBoundingClientRect().right<=innerWidth));
    await page.screenshot({path:path.join(out,'profile-mobile.png')});
    await page.getByRole('button',{name:'关闭个人主页'}).click();
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('#settings').click();await page.locator('[data-settings-section="transcriber"]').click();
    await page.getByText('可选：准备本地语音模型',{exact:true}).click();
    assert.equal(prepares,0,'Opening settings must never download a model');
    await page.locator('#prepareLocalAsr').click();await page.getByText('下载请求已接收',{exact:false}).waitFor();assert.equal(prepares,1);
    assert.deepEqual(errors,[]);

    const ext=await browser.newPage({viewport:{width:390,height:1000}});
    ext.setDefaultTimeout(8000);
    ext.on('pageerror',e=>errors.push(e.message));
    await ext.route('**/__extension/*',route=>{
      const file=path.basename(new URL(route.request().url()).pathname);
      const icon=/^icon(?:16|32|48|128|256|512)\.png$/.test(file);
      assert(icon || ['sidepanel.html','sidepanel.css','sidepanel.js'].includes(file));
      return route.fulfill({body:fs.readFileSync(path.join(__dirname,'../extension',icon?'icons':'',file)),contentType:icon?'image/png':file.endsWith('.html')?'text/html':file.endsWith('.css')?'text/css':'application/javascript'});
    });
    await ext.route('**/health',r=>r.fulfill({json:{ok:true,service:'learnnote',app_version:'0.2.8',backend_version:'0.2.8',protocol_version:1,llm_model_configured:true,default_llm_model:'验收模型',default_llm_supports_vision:true}}));
    await ext.addInitScript(()=>{
      const url='https://www.bilibili.com/video/av117233128837493';
      window.testSeeks=[];
      const cues=Array.from({length:30},(_,i)=>({start:i*10,end:i*10+9,text:i===20?'关键词：音乐需要与角色的情绪相连。':`第 ${i+1} 句，来自视频的原始字幕，保留上下文和时间。`}));
      window.chrome={storage:{local:{get:async defaults=>({...defaults,backendUrl:'http://127.0.0.1:18956'}),set:async()=>{}}},tabs:{query:async()=>[{id:12,url}],get:async()=>({id:12,url})},runtime:{onMessage:{addListener:()=>{}},sendMessage:async message=>{
        if(message.type==='get-current-context')return {tab:{id:12,url,title:'验收视频 · 音乐创作'},page:{page_url:url,title:'验收视频 · 音乐创作',active_video:{src:'https://example.test/video.mp4',duration:300,paused:false},browser_subtitles:cues},resources:[]};
        if(message.type==='seek-current-video'){window.testSeeks.push(message);return {ok:true};}
        if(message.type==='preflight-current-page')return {report:{ok:true,ready:true}};
        return {};
      }}};
    });
    await ext.goto(base+'/__extension/sidepanel.html');
    try { await ext.locator('#sourcePreviewCard:not([hidden])').waitFor(); }
    catch(e) { console.error(errors,await ext.locator('body').innerText()); throw e; }
    assert(await ext.locator('.subtitle-paragraph').count()>1);
    await ext.locator('#subtitleSearch').fill('关键词');
    const cue=ext.locator('#sourcePreviewContent [data-seek-time]');
    await cue.waitFor();assert.equal(await cue.count(),1);await cue.click();
    assert.equal((await ext.evaluate(()=>window.testSeeks))[0].seconds,200);
    assert.match((await ext.evaluate(()=>window.testSeeks))[0].expectedUrl,/av117233128837493/);
    await ext.screenshot({path:path.join(out,'extension-preview.png'),fullPage:true});
    assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,checks:['profile stats and mobile layout','no automatic model downloads','explicit model prepare','subtitle paragraphs and search','source-bound timestamp seek','no page errors'],out},null,2));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
