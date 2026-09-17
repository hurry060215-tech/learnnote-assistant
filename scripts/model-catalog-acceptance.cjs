const {chromium}=require('playwright');const assert=require('node:assert/strict');const fs=require('node:fs');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1280,height:900},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/model/connection',route=>route.fulfill({json:{configured:true,storage:'system',model:{provider:'deepseek',base_url:'https://api.deepseek.com',model:'deepseek-flash',use_saved_connection:true}}}));
 let imageCalls=0;
 await page.route('**/api/model/setup/check',route=>{const p=route.request().postDataJSON();assert.equal(p.api_key,'');if(p.mode==='vision'){imageCalls++;return route.fulfill({json:{ok:true,mode:'vision',message:'图片识别测试通过',supports_vision:true}});}return route.fulfill({json:{ok:true,models:['deepseek-flash','deepseek-v4-pro'],model_details:[{id:'deepseek-flash',vision:true,capability_source:'official_catalog',capability_label:'支持图片 · 官方说明'},{id:'deepseek-v4-pro',vision:null,capability_source:'unknown',capability_label:'视觉能力待测试'}],message:'已发现 2 个模型。'}});});
 await page.goto(process.argv[2]||'http://127.0.0.1:18970');await page.locator('#settings').click();await page.locator('[data-settings-section="model"]').click();
 await page.locator('#discoverModelList').click();await page.locator('#modelChoice option[value="deepseek-v4-pro"]').waitFor({state:'attached'});
 await page.locator('#modelChoice').selectOption('deepseek-flash');assert.equal(await page.locator('#model').inputValue(),'deepseek-flash');assert.match(await page.locator('#modelCapabilityInfo').innerText(),/官方/);
 await page.locator('#testVisionModel').click();await page.locator('#modelCapabilityInfo').filter({hasText:'图片识别已实测'}).waitFor();assert.equal(imageCalls,1);
 await page.locator('#model').fill('my-custom-model');assert.match(await page.locator('#modelCapabilityInfo').innerText(),/尚未读取/);
 await page.locator('#modelChoice').selectOption('deepseek-flash');fs.mkdirSync('build/model-catalog',{recursive:true});await page.screenshot({path:'build/model-catalog/settings.png'});
 await page.locator('#provider').selectOption('openai');assert.equal(await page.locator('#modelChoice option').count(),1,'provider change must clear the previous catalog');assert.deepEqual(errors,[]);
 console.log('PASS: live model choices, documented versus tested vision, custom ID, provider isolation, no browser key persistence');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
