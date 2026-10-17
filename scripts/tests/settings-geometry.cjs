const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../accessibility-visual-acceptance.cjs'),'utf8');
const defaults={overflowX:'visible',overflowY:'visible',display:'block',position:'static',width:'768px',marginLeft:'0px',marginRight:'0px',gridColumn:'auto',zoom:'1'};
const node=(id,left,width,css={},parent=null)=>({id,tagName:'DIV',clientWidth:width,scrollWidth:width,parentElement:parent,css:{...defaults,...css},getBoundingClientRect:()=>({left,right:left+width,top:0,bottom:40,width,height:40})});
const root=node('root',0,768,{overflowX:'hidden'}),settings=node('settingsView',76,768,{marginLeft:'76px'},root),button=node('saveSettingsButton',760,80,{},settings);
const context={require:n=>n==='playwright'?{}:require(n),innerWidth:768,innerHeight:1024,devicePixelRatio:1,visualViewport:{scale:1},getComputedStyle:n=>n.css,
 document:{body:{css:defaults,dataset:{uiDensity:'200'}},documentElement:root,querySelectorAll:s=>s==='#settingsView'?[settings]:s==='#saveSettingsButton'?[button]:[]},module:{exports:{}}};
vm.runInNewContext(source.slice(0,source.indexOf('async function auditViewport'))+'\nmodule.exports=settingsGeometry;',context);
const result=context.module.exports();assert.equal(result.dpr,1);assert.equal(result.cssZoom,'1');assert.equal(result.uiDensity,'200');assert.match(result.method,/not native browser zoom/);
const saved=result.elements.find(x=>x.selector==='#saveSettingsButton');assert.equal(saved.outsideViewportX,true);assert.equal(saved.right,840);assert.equal(saved.clippingAncestors[0].id,'root');assert.equal(saved.clippingAncestors[0].overflowX,'hidden');
assert.equal(root.scrollWidth,768,'Root overflow can be false while a descendant is clipped');
assert(source.indexOf('geometry.json`')<source.indexOf('if (!result.settingsVisible)'), 'Geometry survives existing assertion failures');
assert(source.includes('result.horizontalOverflow || result.menuScrollWidth > result.menuWidth + 1'));
assert(source.includes('output,100)'));assert(source.includes('scale = 200'));
console.log('Settings diagnostics retain app-scale/viewport distinction and expose descendant clipping despite root-width equality');
