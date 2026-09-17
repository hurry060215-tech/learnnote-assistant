const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
(async()=>{
 const base=process.argv[2]||'http://127.0.0.1:18970',out=process.argv[3]||path.join(os.tmpdir(),'learnnote-readable-ui');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:960},reducedMotion:'reduce'});page.setDefaultTimeout(12000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.locator('#settings').click();
  for(const section of ['updates','model','usage','transcriber','notes','processing','appearance','storage']) {
   const tab=page.locator(`[data-settings-section="${section}"]`);await tab.click();
   assert.equal(await tab.getAttribute('aria-pressed'),'true');
   assert(await page.locator(`[data-settings-page="${section}"]`).isVisible());
  }
  await page.locator('[data-settings-section="model"]').click();
  assert.equal(await page.locator('.model-route-panel').evaluate(el=>el.open),false);
  await page.locator('.model-route-panel > summary').click();
  assert.equal(await page.locator('.model-route-panel').evaluate(el=>el.open),true);
  await page.locator('[data-settings-section="appearance"]').click();
  await page.locator('#boldReadingPreset').click();
  assert.equal(await page.locator('#prefWeight').inputValue(),'600');
  assert.equal(await page.locator('#prefLeading').inputValue(),'1.65');
  await page.locator('#savePreferences').click();
  await page.screenshot({path:path.join(out,'reading-settings.png')});
  await page.locator('#settingsDialog header button').click();
  await page.locator('#newNote').click();
  for(const mode of ['url','file','browser']) {
   const button=page.locator(`[data-input="${mode}"]`);
   if(await button.count()) await button.click();
  }
  await page.locator('[data-input="file"]').click();
  await page.locator('#file').setInputFiles({name:'排版验收.md',mimeType:'text/markdown',buffer:Buffer.from('# 排版验收\n\n## 操作\n\n这是用于界面测试的验收段落，包含**重点内容**和说明。\n\n- 第一项内容\n- 第二项内容\n\n## 核对\n\n检查阅读排版、目录和编辑操作。')});
  await page.locator('#createSubmit').click();await page.locator('#document').getByText(/验收段落/).waitFor();
  let typography=await page.locator('#document').evaluate(el=>{const s=getComputedStyle(el);return{weight:s.fontWeight,leading:parseFloat(s.lineHeight)/parseFloat(s.fontSize)}});
  assert.equal(typography.weight,'600');assert(Math.abs(typography.leading-1.65)<0.02);
  await page.screenshot({path:path.join(out,'reader-light.png')});
  await page.locator('#theme').click();
  const contrast=await page.locator('#document').evaluate(el=>{
   const rgb=v=>v.match(/[\d.]+/g).slice(0,3).map(Number);
   const luminance=v=>rgb(v).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
   const style=getComputedStyle(el),a=luminance(style.color),b=luminance(style.backgroundColor);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
  });assert(contrast>=4.5);
  await page.screenshot({path:path.join(out,'reader-dark.png')});await page.locator('#theme').click();
  await page.locator('#openOutline').click();await page.locator('.outline-tree button').first().click();
  await page.locator('#edit').click();assert(await page.locator('#noteText').isVisible());await page.locator('#discard').click();
  await page.locator('#settings').click();
  await page.locator('[data-settings-section="storage"]').click();
  await page.locator('[data-settings-page="storage"] summary').click();
  await page.locator('#studyTools').click();
  await page.getByText('调整每日目标与时区',{exact:true}).waitFor();
  await page.getByText('调整每日目标与时区',{exact:true}).click();assert(await page.locator('#dailyTarget').isVisible());await page.locator('[data-close-tool]').click();
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(out,'reader-mobile.png')});
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,contrast,typography,checks:['eight settings sections','route disclosure','saved reading preset','import switches','document import','outline and edit','study overview','light and dark','mobile overflow'],out},null,2));
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});

