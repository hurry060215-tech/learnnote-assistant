const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();page.setDefaultTimeout(8000);const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
   window.installCalls=0;
   window.pywebview={api:{update_status:async()=>({ok:true,capabilities:{download:true,apply:true},current:{client_version:'0.2.9',extension_version:'0.2.8'},latest:{version:'9.8.7',page_url:'https://github.com/hurry060215-tech/learnnote-assistant/releases/tag/v9.8.7',client:{installable:true,sha256:'a'.repeat(64)},extension:{}},preferences:{auto_check:false,auto_download:false},download:{phase:'ready',path:'test-only',version:'9.8.7'}}),apply_update:async()=>{window.installCalls++;return{ok:true}}}};
  });
  await page.goto(process.argv[2]||'http://127.0.0.1:18961');
  await page.locator('#settings').click();
  await page.locator('[data-settings-section="notes"]').click();
  const originalPrompt=await page.locator('#prefCustom').inputValue();
  await page.locator('#prefCustom').fill('未保存的设置');
  await page.locator('[data-settings-section="updates"]').click();
  await page.locator('#applyUpdate').click();
  assert.equal(await page.evaluate(()=>window.installCalls),0);
  await page.getByText('请先保存未完成的编辑与设置，再进行更新。',{exact:true}).waitFor();
  await page.locator('[data-settings-section="notes"]').click();
  await page.locator('#prefCustom').fill(originalPrompt);
  await page.locator('[data-settings-section="updates"]').click();
  await page.locator('#applyUpdate').click();
  await page.waitForFunction(()=>window.installCalls===1);
  assert.equal(await page.locator('#applyUpdate').isDisabled(),true);
  assert.deepEqual(errors,[]);
  const web=await browser.newPage();web.setDefaultTimeout(8000);
  web.on('pageerror',e=>errors.push(e.message));
  let httpInstalls=0;
  await web.route('**/api/update/status*',r=>r.fulfill({json:{ok:true,current:{client_version:'0.2.9'},capabilities:{desktop_controller:true,download:true,apply:true},latest:{version:'9.8.7',client:{sha256:'a'.repeat(64)}},preferences:{auto_check:false,auto_download:false},download:{phase:'ready',path:'owned-test-path',version:'9.8.7'}}}));
  await web.route('**/api/update/intent',r=>r.fulfill({json:{token:'test-intent'}}));
  await web.route('**/api/update/action',r=>{
   assert.equal(r.request().headers()['x-learnnote-update-intent'],'test-intent');
   assert.deepEqual(r.request().postDataJSON(),{component:'client',action:'apply',version:'9.8.7'});
   httpInstalls++;return r.fulfill({json:{ok:true}});
  });
  await web.goto(process.argv[2]||'http://127.0.0.1:18961');
  await web.locator('#settings').click();await web.locator('[data-settings-section="updates"]').click();
  await web.locator('#applyUpdate').click();
  await web.getByText('更新已排队，客户端将在关闭后安装并重新启动。',{exact:true}).waitFor();
  assert.equal(httpInstalls,1);assert.deepEqual(errors,[]);
  const out=path.resolve(process.argv[3]||'build/update-center-ui');fs.mkdirSync(out,{recursive:true});
  for(const platform of ['macOS','Linux']) {
   const unsupported=await browser.newPage({viewport:{width:platform==='macOS'?1280:390,height:844},reducedMotion:'reduce'});
   unsupported.setDefaultTimeout(8000);
   unsupported.on('pageerror',e=>errors.push(e.message));
   async function openSettings() {
    await unsupported.waitForFunction(()=>Boolean(window.LearnNoteSettings)&&Boolean(document.querySelector('#homeUrlForm'))&&!document.querySelector('#welcome').hidden);
    if(await unsupported.locator('#menu').getAttribute('aria-expanded')!=='true') await unsupported.locator('#menu').click();
    await unsupported.waitForFunction(()=>document.querySelector('#menu').getAttribute('aria-expanded')==='true'&&!document.querySelector('#sidebar').inert);
    const bounds=await unsupported.locator('#settings').boundingBox();
    assert(bounds&&bounds.x>=0&&bounds.x+bounds.width<=unsupported.viewportSize().width);
    await unsupported.locator('#settings').click();
    await unsupported.locator('[data-settings-section="updates"]').click();
   }
   const guidance='当前平台不支持 Windows 安装包自动更新。请查看官方版本说明，按 macOS / Linux 部署文档手动更新，并保留原数据目录。';
   await unsupported.addInitScript(({guidance})=>{
    window.updateActions=0;
    window.pywebview={api:{update_status:async()=>({ok:true,current:{client_version:'0.2.9'},client_update_available:true,capabilities:{download:false,apply:false,reason:'unsupported_platform',manual_update_message:guidance},latest:{version:'9.8.7',page_url:'https://github.com/hurry060215-tech/learnnote-assistant/releases/tag/v9.8.7',client:{installable:false,url:'',sha256:''},extension:{}},preferences:{auto_check:false,auto_download:true},download:{phase:'ready',path:'copied-windows.exe',version:'9.8.7'}}),start_update_download:async()=>{window.updateActions++;return{}},apply_update:async()=>{window.updateActions++;return{ok:true}}}};
   },{guidance});
   await unsupported.goto(process.argv[2]||'http://127.0.0.1:18961');
   await openSettings();
   await unsupported.locator('#checkUpdates').click();
   await unsupported.getByText(guidance,{exact:false}).waitFor();
   assert.equal(await unsupported.locator('#downloadUpdate').isVisible(),false);
   assert.equal(await unsupported.locator('#applyUpdate').isVisible(),false);
   assert.equal(await unsupported.locator('#updateAutoDownload').isDisabled(),true);
   assert.equal(await unsupported.locator('#updateReleaseLink').getAttribute('href'),'https://github.com/hurry060215-tech/learnnote-assistant/releases/tag/v9.8.7');
   await unsupported.evaluate(()=>{document.querySelector('#downloadUpdate').click();document.querySelector('#applyUpdate').click()});
   assert.equal(await unsupported.evaluate(()=>window.updateActions),0);
   await unsupported.locator('#settingsDialog').screenshot({path:path.join(out,platform.toLowerCase()+'-manual-update.png')});
   await unsupported.keyboard.press('Escape');
   await openSettings();
   assert.equal(await unsupported.locator('#applyUpdate').isVisible(),false);
   await unsupported.close();
  }
  assert.deepEqual(errors,[]);
  console.log('PASS: actual update button, unsaved settings protection, no duplicate installation; no real installer executed');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
