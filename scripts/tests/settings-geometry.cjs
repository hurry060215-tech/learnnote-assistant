const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../accessibility-visual-acceptance.cjs'),'utf8');
const defaults={overflowX:'visible',overflowY:'visible',display:'block',position:'static',width:'768px',marginLeft:'0px',marginRight:'0px',gridColumn:'auto',zoom:'1'};
const node=(id,left,width,css={},parent=null)=>({id,tagName:'DIV',clientWidth:width,scrollWidth:width,parentElement:parent,css:{...defaults,...css},getBoundingClientRect:()=>({left,right:left+width,top:0,bottom:40,width,height:40})});
const root=node('root',0,768,{overflowX:'hidden'}),settings=node('settingsView',76,768,{marginLeft:'76px'},root),button=node('saveSettingsButton',760,80,{},settings);
const context={NodeFilter:{SHOW_TEXT:4},require:n=>n==='playwright'?{}:require(n),innerWidth:768,innerHeight:1024,devicePixelRatio:1,visualViewport:{scale:1},getComputedStyle:n=>n.css,
 document:{createTreeWalker:()=>({nextNode:()=>false}),body:{css:defaults,dataset:{uiDensity:'200'}},documentElement:root,querySelectorAll:s=>s==='#settingsView'?[settings]:s==='#saveSettingsButton'?[button]:[]},module:{exports:{}}};
vm.runInNewContext(source.slice(0,source.indexOf('async function auditViewport'))+'\nmodule.exports=settingsGeometry;',context);
const result=context.module.exports();assert.equal(result.dpr,1);assert.equal(result.cssZoom,'1');assert.equal(result.uiDensity,'200');assert.match(result.method,/not native browser zoom/);
const saved=result.elements.find(x=>x.selector==='#saveSettingsButton');assert.equal(saved.outsideViewportX,true);assert.equal(saved.right,840);assert.equal(saved.clippingAncestors[0].id,'root');assert.equal(saved.clippingAncestors[0].overflowX,'hidden');
assert.equal(root.scrollWidth,768,'Root overflow can be false while a descendant is clipped');
assert(source.indexOf('geometry.json`')<source.indexOf('if (!result.settingsVisible)'), 'Geometry survives existing assertion failures');
assert(source.includes('result.horizontalOverflow || result.menuScrollWidth > result.menuWidth + 1'));
assert(source.includes('output,100)'));assert(source.includes('scale = 200'));
console.log('Settings diagnostics retain app-scale/viewport distinction and expose descendant clipping despite root-width equality');

vm.runInNewContext('module.exports=assertSettingsContainment;',context);
const assertContained=context.module.exports;
const required=['#settingsCloseButton','#saveSettingsButton','#settingLocale','[data-setting="uiScale"]'];
const fixture=(width,scale)=>({viewport:{width,height:1024},uiDensity:String(scale),elements:required.map(selector=>({selector,width:100,height:40,left:100,right:200,outsideViewportX:false,clippingAncestors:[]}))});
for (const width of [390,681,768,900,1440]) for (const scale of [100,200]) {
  const clean=fixture(width,scale);assert.doesNotThrow(()=>assertContained(clean));
  const overflow=fixture(width,scale);overflow.elements[0].outsideViewportX=true;
  assert.throws(()=>assertContained(overflow),/horizontally clipped/);
  const hidden=fixture(width,scale);hidden.elements[1].clippingAncestors=[{left:0,right:180,overflowX:'hidden'}];
  assert.throws(()=>assertContained(hidden),/horizontally clipped/);
}
const missing=fixture(768,200);missing.elements.pop();assert.throws(()=>assertContained(missing),/Missing visible/);
const hiddenCheckbox=fixture(768,200);hiddenCheckbox.elements.push({selector:'.settings-pane:not([hidden]) input[type="checkbox"]',width:0,height:0,outsideViewportX:true});assert.doesNotThrow(()=>assertContained(hiddenCheckbox));
const visibleCheckbox=fixture(768,200);visibleCheckbox.elements.push({selector:'.settings-pane:not([hidden]) input[type="checkbox"]',width:46,height:25,outsideViewportX:true,clippingAncestors:[]});assert.throws(()=>assertContained(visibleCheckbox),/horizontally clipped/);
assert(source.indexOf('geometry.json`')<source.indexOf('assertSettingsContainment(geometry);'));
assert(source.includes('for (const width of [681, 900])'));
const css=fs.readFileSync(path.join(__dirname,'../../web/experience.css'),'utf8');
const correction='body[data-app-view="settings"]:not(.reading-mode):not(.assistant-open) .settings-view {\n    width: calc(100% - var(--mature-nav));\n  }';
for (const represented of [css, css.replace(/\r\n/g,'\n').replace(/\n/g,'\r\n')]) {
  const normalized=represented.replace(/\r\n/g,'\n');
  const tablet=normalized.slice(normalized.lastIndexOf('@media (min-width: 681px) and (max-width: 900px)'));
  assert(tablet.includes(correction));assert(tablet.indexOf(correction)>tablet.indexOf('width: 100%;'));
}
const mature=fs.readFileSync(path.join(__dirname,'../../web/mature.css'),'utf8');assert(mature.includes('margin-left: var(--mature-nav);'));
assert(fs.readFileSync(path.join(__dirname,'../../web/classic.html'),'utf8').includes('experience.css?v=20261017-settings-button-height'));
console.log('Settings control bounds reject viewport and hidden-ancestor clipping at both scales; tablet width correction retains the fixed rail and exact breakpoint scope');

vm.runInNewContext('module.exports=assertSettingsButtonLabels;',context);
const labels=context.module.exports;
const buttons=height=>({elements:['settingsCloseButton','resetSettingsButton','saveSettingsButton'].map(id=>({selector:'#'+id,left:20,right:255,width:235,top:77,bottom:77+height,height,textRects:[{left:40,right:235,top:79,bottom:110},{left:60,right:215,top:110,bottom:141}]}))});
assert.throws(()=>labels(buttons(44)),/text escapes/,'Actual 44px mobile box cannot contain two 30px lines');
assert.doesNotThrow(()=>labels(buttons(66)));
const above=buttons(66);above.elements[0].textRects[0].top=74;assert.throws(()=>labels(above),/text escapes/);
const sideways=buttons(66);sideways.elements[1].textRects[0].right=258;assert.throws(()=>labels(sideways),/text escapes/);
const empty=buttons(66);empty.elements[2].textRects=[];assert.throws(()=>labels(empty),/Missing readable/);
const mobileRule='.settings-header .action-button,\n  .settings-actions .action-button {\n    height: auto;\n    min-height: max(44px, var(--appearance-control-height));\n  }';
for(const represented of [css,css.replace(/\r\n/g,'\n').replace(/\n/g,'\r\n')]) {
 const normalized=represented.replace(/\r\n/g,'\n');assert(normalized.includes('@media (max-width: 680px) {\n  '+mobileRule));
}
assert(source.includes("await page.keyboard.press('Tab')"));assert(source.includes("await page.keyboard.press('Shift+Tab')"));
assert(source.includes("next !== 'saveSettingsButton'"));assert(source.includes('fullPage:false'));
console.log('Mobile settings labels reject vertical and horizontal text escape; auto height retains target size and scoped breakpoint');
