const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(root,'build','captions-panel');fs.mkdirSync(out,{recursive:true});
 const server=http.createServer((req,res)=>{const file=path.resolve(root,'.'+new URL(req.url,'http://localhost').pathname);if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':file.endsWith('.png')?'image/png':'text/html');fs.createReadStream(file).pipe(res);});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:390,height:900},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
   const url='https://www.bilibili.com/video/BV1ABCDEF123/';
   const context={tab:{id:1,url,title:'如何把视频变成有用的学习笔记'},page:{page_url:url,title:'如何把视频变成有用的学习笔记',active_video:{duration:120,current_time:0},subtitle_probe:{status:'ready',elapsed_ms:380},browser_subtitles:Array.from({length:24},(_,i)=>({start:i*5,end:i*5+5,text:`第 ${i+1} 句：先理解核心观点，再回到原文核对。`}))},resources:[]};
   window.chrome={storage:{local:{get:async defaults=>({...defaults}),set:async()=>{}}},tabs:{query:async()=>[]},runtime:{onMessage:{addListener(){}},sendMessage:async msg=>msg.type==='get-current-context'?context:{ok:true}},i18n:{getMessage:()=>''}};
  });
  let releaseConnection;const connection=new Promise(resolve=>{releaseConnection=resolve});
  await page.route('http://127.0.0.1:8765/**',async route=>{const u=route.request().url();if(u.endsWith('/health'))await connection;return route.fulfill({json:u.endsWith('/health')?{service:'learnnote',app_version:'0.2.10',protocol_version:1}:{configured:true,model:{model:'fixture'}}});});
  await page.goto(`http://127.0.0.1:${port}/extension/sidepanel.html`);
  await page.locator('#sourcePreviewCard').waitFor({state:'visible',timeout:12000});
  assert(!await page.locator('#connectionTitle').innerText().then(t=>t.includes('已连接')),'subtitle preview must appear before slow backend discovery');
  releaseConnection();
  assert.match(await page.locator('#preflightMessage').innerText(),/24.*0.4/);
  const order=await page.evaluate(()=>document.querySelector('#sourcePreviewCard').compareDocumentPosition(document.querySelector('.handoff-card')));
  assert(order & 4,'transcript preview should precede generation choices');
  await page.locator('#sourcePreviewCard > summary').click();
  await page.locator('#subtitleSearch').fill('第 7 句');assert.match(await page.locator('#sourcePreviewContent').innerText(),/第 7 句/);
  await page.locator('#subtitleSearch').fill('');await page.screenshot({path:path.join(out,'panel.png'),fullPage:true});
  await page.locator('#sourcePreviewCard > summary').click();await page.screenshot({path:path.join(out,'panel-compact.png'),fullPage:true});
  await page.setViewportSize({width:320,height:740});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,checks:['captions before backend','actual timing','preview before generation','search','320px overflow'],out}));
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1});
