// Pure contract tests only; native input and real rendering require Windows CI.
const assert = require('node:assert/strict');
const { PERCENTAGES, assertZoomMetrics, assertSecondaryLayout, waitForNativePreset } = require('../timeline-native-zoom-matrix.cjs');
const baseline = {width:1016,height:636,dpr:1,cssZoom:'1',documentZoom:'1',visualScale:1,overflow:0};
const state = percent => ({...baseline,width:Math.round(baseline.width/(percent/100)),height:Math.round(baseline.height/(percent/100)),dpr:percent/100});
assert.deepEqual(PERCENTAGES,[90,125,150]);
for (const percent of [...PERCENTAGES,100,200]) {
  assertZoomMetrics(state(percent),baseline,percent);
  for (const change of [{dpr:3},{width:2000},{height:2000},{cssZoom:'2'},{documentZoom:'1.25'},{visualScale:1.5},{overflow:3}])
    assert.throws(()=>assertZoomMetrics({...state(percent),...change},baseline,percent));
}
const box={left:10,right:110,top:10,bottom:50,width:100,height:40,client:100,scroll:100};
const layout={width:508,height:318,open:true,menu:box,controls:[box,box]};
assertSecondaryLayout(layout);
for(const change of [{left:-2},{right:510},{bottom:320},{top:-2},{width:0},{scroll:103}])
  assert.throws(()=>assertSecondaryLayout({...layout,controls:[{...box,...change}]}));
assert.throws(()=>assertSecondaryLayout({...layout,open:false}));
(async()=>{
 let waited=false;
 const actual=await waitForNativePreset({waitForFunction:async(fn,arg)=>{assert.equal(typeof fn,'function');assert.deepEqual(arg,{initial:baseline,ratio:.9});waited=true;}},async()=>state(90),baseline,90);
 assert(waited);assert.equal(actual.dpr,.9);
 const primary=new Error('native preset did not settle');
 await assert.rejects(waitForNativePreset({waitForFunction:async()=>{throw primary;}},async()=>assert.fail('must not read after timeout'),baseline,90),e=>e===primary);
 console.log('Native preset metrics, CSS/pinch exclusion, secondary clipping and bounded settle failures pass; no native commands executed');
})().catch(e=>{console.error(e);process.exitCode=1;});

// Execute the orchestration with explicit inert adapters; screenshots are fake PNG headers.
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
async function exerciseMatrix(failAt) {
  const calls=[],records=[],primary=new Error('PRIMARY_'+failAt);let zoom=100,open=false;
  const png=Buffer.alloc(24);Buffer.from([137,80,78,71,13,10,26,10]).copy(png);png.write('IHDR',12);png.writeUInt32BE(1024,16);png.writeUInt32BE(768,20);
  const sandbox={module:{exports:{}},require:name=>{
    if(name==='node:fs')return {readFileSync:()=>png};
    if(name==='./timeline-native-capture.cjs')return {pngSize:require('../timeline-native-capture.cjs').pngSize,captureNativeViews:async(_page,options)=>{calls.push('source:'+options.percent);if(failAt==='source')throw primary;assert.equal(options.percent,zoom);}};
    return require(name);
  }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../timeline-native-zoom-matrix.cjs'),'utf8'),sandbox);
  const locator=selector=>({click:async()=>calls.push('click:'+selector),focus:async()=>calls.push('focus:'+selector),isVisible:async()=>{if(failAt==='menu')throw primary;return true;},
    evaluate:async fn=>String(fn).includes('node.open')?open:true});
  const page={locator,bringToFront:async()=>{},waitForFunction:async()=>{},evaluate:async fn=>{
    if(fn.name==='secondaryLayout')return layout;
    return true;
  },keyboard:{press:async key=>{if(failAt==='keyboard')throw primary;calls.push('key:'+key);if(key==='Escape')open=false;else if(key==='Enter')open=true;}}};
  const nativeKey=(value)=>{calls.push('native:'+value);if(value==='capture'){if(failAt==='capture')throw primary;return {width:1024,height:768,sampled_colors:2};}if(value==='reset'&&failAt==='reset')throw primary;zoom=value==='reset'?100:Number(value);return {requested_percent:zoom};};
  const promise=sandbox.module.exports.runNativeZoomMatrix({page,marker:locator('marker'),nativeKey,metrics:async()=>state(zoom),baseline,out:'/never-written',cases:records});
  if(failAt) {await assert.rejects(promise,e=>e===primary);assert.equal(records.length,1);}
  else {await promise;assert.deepEqual(records.map(r=>r.percent),[90,125,150]);assert.equal(zoom,100);assert.equal(calls.filter(c=>c==='native:reset').length,3);assert(records.every(r=>r.keyboard_source_seek&&r.keyboard_first_cue&&r.keyboard_secondary_actions&&r.restored.dpr===1));}
}
(async()=>{for(const failure of [null,'keyboard','source','menu','capture','reset'])await exerciseMatrix(failure);console.log('Six native matrix orchestration cases pass with inert adapters; no browser/native input');})().catch(e=>{console.error(e);process.exitCode=1;});
