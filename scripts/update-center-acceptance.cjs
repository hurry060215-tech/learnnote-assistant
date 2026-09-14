const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();page.setDefaultTimeout(8000);const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
   window.installCalls=0;
   window.pywebview={api:{update_status:async()=>({ok:true,current:{client_version:'0.2.9',extension_version:'0.2.8'},latest:{version:'9.8.7',page_url:'https://github.com/hurry060215-tech/learnnote-assistant/releases/tag/v9.8.7',client:{installable:true,sha256:'a'.repeat(64)},extension:{}},preferences:{auto_check:false,auto_download:false},download:{phase:'ready',path:'test-only',version:'9.8.7'}}),apply_update:async()=>{window.installCalls++;return{ok:true}}}};
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
  console.log('PASS: actual update button, unsaved settings protection, no duplicate installation; no real installer executed');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
