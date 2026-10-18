// Fault injection only. No browser is launched and native key input is forbidden.
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const sourcePath = path.join(__dirname, "../timeline-native-zoom-acceptance.cjs");
const sourceRequire = require("node:module").createRequire(sourcePath);
const source = fs.readFileSync(sourcePath, "utf8");
const realFollow = sourceRequire("./claim-follow-visibility-acceptance.cjs");
assert.equal(realFollow, require("../claim-follow-visibility-acceptance.cjs"));
assert.equal(typeof realFollow.assertClaimFollowVisibility, "function");

async function probe({ failureAt = "newPage", reportFails = false, closeFails = false }) {
  const calls = [], diagnostics = [], primary = new Error(`PRIMARY_${failureAt}`);
  const failAt = key => { if (failureAt === key) throw primary; };
  const close = key => async () => { calls.push(`${key}.close`); if (closeFails) throw new Error(`${key}_CLOSE_FAILURE`); };
  const server = {process: () => { failAt("process"); return {pid: 12345}; }, wsEndpoint: () => "owned-fixture", close: close("server")};
  const context = {setDefaultTimeout: timeout => assert.equal(timeout, 15000), route: async () => failAt("route"), newPage: async () => { failAt("newPage"); throw new Error("Unexpected browser setup continuation"); }, close: close("context")};
  const browser = {newContext: async () => { failAt("newContext"); return context; }, close: close("browser")};
  const sandbox = {module: {exports: {}}, process: {platform: "win32"}, URL, __dirname: "/not-executed",
    console: {error: (...args) => diagnostics.push(args.map(String).join(" "))},
    require: name => {
      if (name === "./timeline-native-zoom-matrix.cjs") return require("../timeline-native-zoom-matrix.cjs");
      if (name === "./timeline-native-capture.cjs") return require("../timeline-native-capture.cjs");
      if (name === "playwright") return {chromium: {launchServer: async () => server, connect: async () => { failAt("connect"); return browser; }}};
      if (name === "node:fs") return {writeFileSync: () => { if (reportFails) throw new Error("REPORT_WRITE_FAILURE"); }};
      if (name === "node:child_process") return {execFileSync: () => { assert.fail("Native commands forbidden in fault-injection tests"); }};
      return sourceRequire(name);
    }};
  vm.runInNewContext(source, sandbox);
  await assert.rejects(sandbox.module.exports.assertNativeTimelineZoom({base: "http://127.0.0.1:8765", taskId: "fixture", claimId: "fixture", out: "/not-written"}), error => error === primary);
  const expected = ["process", "connect"].includes(failureAt) ? ["server.close"]
    : failureAt === "newContext" ? ["browser.close", "server.close"] : ["context.close", "browser.close", "server.close"];
  assert.deepEqual(calls, expected, "Every created browser resource must be closed after failure");
  assert.equal(diagnostics.length, reportFails ? (closeFails ? 2 : 1) : 0);
}

(async () => {
  for (const failureAt of ["process", "connect", "newContext", "route", "newPage"])
    for (const reportFails of [false, true])
      for (const closeFails of [false, true]) await probe({failureAt, reportFails, closeFails});
  console.log("Native zoom failure preservation: 20 mocked cases passed; no native commands executed");
})().catch(error => { console.error(error); process.exitCode = 1; });

async function lateProbe({matrixFailure=false,resetFailure=false,closeFailure=false,translationFailure=false,prepareFailure=false,followFailure=false}) {
  const primary=new Error(translationFailure?'PRIMARY_TRANSLATION':followFailure?'PRIMARY_FOLLOW':'PRIMARY_MATRIX'),resetError=new Error('RESET_FAILED'),calls=[],writes=[];
  primary.code='ETIMEDOUT';primary.stderr='private arbitrary stderr\r\nLN_NATIVE_PHASE:entered|0\r\nLN_NATIVE_PHASE:native-type-compile|100\r\n';
  let zoom=100,lastKey='',resets=0,followCalls=0;
  const baseline={width:1000,height:600,dpr:1,cssZoom:'1',documentZoom:'1',visualScale:1,overflow:0};
  const close=key=>async()=>{calls.push(key);if(closeFailure)throw new Error('CLOSE_'+key);};
  const node={first:()=>node,click:async()=>{},focus:async()=>{},evaluate:async()=>true};
  const page={on:()=>{},goto:async()=>{},locator:()=>node,bringToFront:async()=>{},waitForFunction:async()=>{},isClosed:()=>false,screenshot:async()=>{},
    keyboard:{press:async key=>{lastKey=key;}},evaluate:async fn=>{
      const body=String(fn);
      if(body.includes('width: innerWidth'))return {...baseline,width:1000/(zoom/100),height:600/(zoom/100),dpr:zoom/100};
      if(body.includes('getAttribute("aria-label")'))return lastKey==='End'?'203/203':'1/203';
      if(body.includes('dataset.cueIndex'))return '0';
    }};
  const context={setDefaultTimeout:()=>{},route:async()=>{},newPage:async()=>page,close:close('context')};
  const browser={newContext:async()=>context,version:()=> 'fixture',close:close('browser')};
  const server={process:()=>({pid:12345}),wsEndpoint:()=> 'owned',close:close('server')};
  const sandbox={module:{exports:{}},process:{platform:'win32'},URL,__dirname:'/not-executed',console:{error:()=>{}},require:name=>{
    if(name==='./timeline-native-zoom-matrix.cjs')return {runNativeZoomMatrix:async({nativeKey})=>{if(matrixFailure)throw primary;for(const action of ['90','125','150'])nativeKey(action);},waitForNativePreset:require('../timeline-native-zoom-matrix.cjs').waitForNativePreset};
    if(name==='./timeline-native-capture.cjs')return {captureNativeViews:async(_page,{nativeCapture})=>{nativeCapture('synthetic.png');}};
    // Geometry has its own executable suite. This seam tests wrapper lifecycle,
    // while the real helper module/export is still resolved and checked above.
    if(name==='./claim-follow-visibility-acceptance.cjs')return {assertClaimFollowVisibility:async(receivedPage,options)=>{
      followCalls++;assert.equal(receivedPage,page);assert.equal(options.claimId,'fixture');assert.equal(options.oversizedClaimId,'oversized-fixture');
      assert.equal(options.out,'/not-written');assert.equal(options.name,'follow-native-200');assert(Array.isArray(options.records));assert.equal(typeof options.capture,'function');
      if(followFailure)throw primary;
    }};
    if(name==='playwright')return {chromium:{launchServer:async()=>server,connect:async()=>browser}};
    if(name==='node:fs')return {writeFileSync:(_path,data)=>writes.push(JSON.parse(data))};
    if(name==='node:child_process')return {execFileSync:(_exe,args,options)=>{const action=args[args.indexOf('-Zoom')+1];assert.equal(options.timeout,action==='prepare'?45000:15000);calls.push(action);if(action==='prepare'&&prepareFailure)throw primary;if(action==='dismiss-translation'&&translationFailure)throw primary;if(action==='reset'){resets++;if(resets>1&&resetFailure)throw resetError;zoom=100;}if(action==='200')zoom=200;return '{}';}};
    return sourceRequire(name);
  }};
  vm.runInNewContext(source,sandbox);
  const promise=sandbox.module.exports.assertNativeTimelineZoom({base:'http://127.0.0.1:8765',taskId:'fixture',claimId:'fixture',oversizedClaimId:'oversized-fixture',out:'/not-written'});
  if(matrixFailure||translationFailure||prepareFailure||followFailure)await assert.rejects(promise,e=>e===primary);
  else if(resetFailure||closeFailure)await assert.rejects(promise,/RESET_FAILED|CLOSE_/);
  else {const result=await promise;assert.deepEqual(JSON.parse(JSON.stringify(result)),writes.at(-1));assert.equal(result.baseline_restored.dpr,1);assert.equal(result.baseline_restored.width,1000);}
  assert.equal(calls.filter(action=>action==='prepare').length,1,'Preparation is never retried');
  assert.equal(followCalls,(matrixFailure||translationFailure||prepareFailure)?0:1,'Follow helper runs exactly once after native captures');
  if(!matrixFailure&&!translationFailure&&!prepareFailure)for(const action of ['90','125','150','200','capture'])assert(calls.includes(action));
  assert.equal(resets,(translationFailure||prepareFailure)?1:2,'Final reset attempted after both successful and failed matrix');
  if(prepareFailure){
    assert(!calls.includes('dismiss-translation'));
    assert.deepEqual(writes.at(-1).native_failures[0],{action:'prepare',code:'ETIMEDOUT',phases:[{phase:'entered',elapsed_ms:0},{phase:'native-type-compile',elapsed_ms:100}],stderr_truncated:false});
    assert(!JSON.stringify(writes).includes('private arbitrary stderr'));
  }else{
    assert(calls.indexOf('prepare') < calls.indexOf('dismiss-translation'));
    assert(calls.indexOf('dismiss-translation') < calls.indexOf('reset'));
  }
  assert.deepEqual(calls.slice(-3),['context','browser','server']);
  if(resetFailure||closeFailure||followFailure)assert.equal(writes.at(-1).passed,false);
}
(async()=>{for(const matrixFailure of [false,true])for(const resetFailure of [false,true])for(const closeFailure of [false,true])await lateProbe({matrixFailure,resetFailure,closeFailure});console.log('Eight late matrix/reset/cleanup cases preserve primary errors and returned/report restoration parity');})().catch(e=>{console.error(e);process.exitCode=1;});

(async()=>{for(const closeFailure of [false,true])await lateProbe({translationFailure:true,closeFailure});console.log("Translation-offer failure preserves primary and closes all owned resources");})().catch(e=>{console.error(e);process.exitCode=1;});

(async()=>{for(const closeFailure of [false,true])await lateProbe({prepareFailure:true,closeFailure});console.log('Prepare timeout retains fixed phases and primary failure with owned cleanup');})().catch(e=>{console.error(e);process.exitCode=1;});

(async()=>{for(const resetFailure of [false,true])for(const closeFailure of [false,true])await lateProbe({followFailure:true,resetFailure,closeFailure});console.log('Four follow-helper failures preserve the primary error through zoom reset and owned cleanup');})().catch(e=>{console.error(e);process.exitCode=1;});
