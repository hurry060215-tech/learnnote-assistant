// Deterministic product tests. All model calls and browser-extension APIs are mocked.
const fs=require('node:fs'), path=require('node:path'), os=require('node:os'), assert=require('node:assert/strict');
function extensionAsset(url) {
  // Keep this finite; new shipped imports need a reviewed fixture entry.
  const allowed = ['sidepanel.html', 'sidepanel.css', 'sidepanel.js', 'sidepanel-progress.js',
    'i18n.js', 'community-source.js', 'sidepanel-community.js'];
  let pathname; try { pathname = new URL(url, 'http://localhost').pathname; } catch { return null; }
  const rawPath = String(url).replace(/^https?:\/\/[^/?#]*/i, '').split(/[?#]/, 1)[0];
  if (rawPath !== pathname || !pathname.startsWith('/__extension/')) return null;
  const file = pathname.slice('/__extension/'.length);
  if (!allowed.includes(file) && !/^icons\/icon(?:16|32|48|128|256|512)\.png$/.test(file)) return null;
  return path.join(__dirname, '../extension', file);
}
async function run() {
  const {chromium}=require('playwright');
  const base=process.argv[2]||'http://127.0.0.1:18956';
  const out=process.argv[3]||fs.mkdtempSync(path.join(os.tmpdir(),'learnnote-core-output-'));fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
    page.setDefaultTimeout(8000);
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    let prepares=0;
    await page.route('**/api/local-models/*/prepare',r=>{prepares++;return r.fulfill({json:{status:'downloading',message:'下载请求已接收'}});});
    await require('./usage-coverage-acceptance.cjs')(page, base, out);
    await page.locator('#settings').click();await page.locator('[data-settings-section="transcriber"]').click();
    await page.getByText('可选：准备本地语音模型',{exact:true}).click();
    assert.equal(prepares,0,'Opening settings must never download a model');
    await page.locator('#prepareLocalAsr').click();await page.getByText('下载请求已接收',{exact:false}).waitFor();assert.equal(prepares,1);
    assert.deepEqual(errors,[]);

    const ext=await browser.newPage({viewport:{width:390,height:1000}});
    ext.setDefaultTimeout(8000);
    ext.on('pageerror',e=>errors.push(e.message));
    await ext.route('**/__extension/**',route=>{
      const file=extensionAsset(route.request().url());
      assert(file, 'Unknown extension fixture asset');
      return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.png')?'image/png':file.endsWith('.html')?'text/html':file.endsWith('.css')?'text/css':'application/javascript'});
    });
    await ext.route('**/health',r=>r.fulfill({json:{ok:true,service:'learnnote',app_version:'0.2.8',backend_version:'0.2.8',protocol_version:1,llm_model_configured:true,default_llm_model:'验收模型',default_llm_supports_vision:true}}));
    await ext.addInitScript(()=>{
      const url='https://www.bilibili.com/video/av117233128837493';
      window.testSeeks=[];
      const cues=Array.from({length:30},(_,i)=>({start:i*10,end:i*10+9,text:i===20?'关键词：音乐需要与角色的情绪相连。':`第 ${i+1} 句，来自视频的原始字幕，保留上下文和时间。`}));
      window.chrome={storage:{local:{get:async defaults=>({...defaults,backendUrl:'http://127.0.0.1:18956'}),set:async()=>{}}},tabs:{query:async()=>[{id:12,url}],get:async()=>({id:12,url})},runtime:{onMessage:{addListener:()=>{}},sendMessage:async message=>{
        if(message.type==='get-current-context')return {tab:{id:12,url,title:'验收视频 · 音乐创作'},page:{page_url:url,title:'验收视频 · 音乐创作',active_video:{current_src:'https://example.test/video.mp4',frame_id:0,frame_url:url,duration:300,paused:false},seek_token:'fixture-video-document',browser_subtitles:cues},resources:[]};
        if(message.type==='seek-current-video'){window.testSeeks.push(message);return {ok:true};}
        if(message.type==='preflight-current-page')return {report:{ok:true,ready:true}};
        return {};
      }}};
    });
    await ext.goto(base+'/__extension/sidepanel.html');
    try { await ext.locator('#sourcePreviewCard:not([hidden])').waitFor(); }
    catch(e) { console.error(errors,await ext.locator('body').innerText()); throw e; }
    assert(await ext.locator('.subtitle-paragraph').count()>1);
    await ext.locator('#sourcePreviewCard > summary').click();
    await ext.locator('#subtitleSearch').fill('关键词');
    const cue=ext.locator('#sourcePreviewContent [data-seek-time]');
    await cue.waitFor();assert.equal(await cue.count(),1);await cue.click();
    const seekMessage=(await ext.evaluate(()=>window.testSeeks))[0];
    assert.equal(seekMessage.seconds,200);assert.equal(seekMessage.targetTabId,12);
    assert.equal(seekMessage.sourceIdentity.tab_id,12);
    assert.match(seekMessage.sourceIdentity.page_url,/av117233128837493/);
    assert.equal(seekMessage.sourceIdentity.canonical_page_url,seekMessage.sourceIdentity.page_url);
    assert.deepEqual(seekMessage.sourceIdentity.active_video,{current_src:'https://example.test/video.mp4',frame_id:0,frame_url:seekMessage.sourceIdentity.page_url,seek_token:'fixture-video-document'});
    assert(await ext.locator('.brand-mark').evaluate(image => image.complete && image.naturalWidth > 0));
    await ext.screenshot({path:path.join(out,'extension-preview.png'),fullPage:true});
    assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,checks:['profile stats and mobile layout','no automatic model downloads','explicit model prepare','subtitle paragraphs and search','mocked source-bound timestamp message','no page errors'],out},null,2));
  } finally {await browser.close();}
}
module.exports = {extensionAsset};
if (require.main === module) run().catch(e=>{console.error(e);process.exitCode=1;});
