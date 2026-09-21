import assert from 'node:assert/strict';
import {createSidepanelHarness,videoContext} from './sidepanel_test_harness.mjs';
const live={service:'learnnote',app_version:'0.2.14',backend_version:'0.2.14',protocol_version:1};
const native=await createSidepanelHarness({contexts:[videoContext()],focus:{ok:true,focused:true}});
await Promise.all([native.api.openClient('task','abc123def456','transcript'),native.api.openClient()]);
assert.equal(native.openedTabs.length,0);
const calls=native.fetchCalls.filter(c=>c.url.endsWith('/api/desktop/focus'));
assert.equal(calls.length,1);
assert.equal(calls[0].options.headers['X-LearnNote-Pairing'],'test-pair');
assert.deepEqual(JSON.parse(calls[0].options.body),{view:'task',task_id:'abc123def456',tab:'transcript'});

const healthByUrl={};
const cold=await createSidepanelHarness({contexts:[videoContext()],healthByUrl,focus:{ok:true,focused:true}});
let launches=0;
cold.context.chrome.tabs.create=async options=>{
 assert.equal(options.url,'learnnote://open?port=8765'); launches++;
 healthByUrl['http://127.0.0.1:8765/health']=live;
};
await Promise.all([cold.api.openClient(),cold.api.openClient()]);
assert.equal(launches,1);
assert.equal(cold.api.getState().clientConnected,true);
assert.equal(cold.elements.get('#clientInstallHelp').hidden,true);
assert.equal(cold.elements.get('#openClientButton').disabled,false);
assert.equal(cold.elements.get('#openClientButton').textContent,'打开工作台');

const blocked=await createSidepanelHarness({contexts:[videoContext()],health:new Error('offline')});
blocked.context.chrome.tabs.create=async()=>{throw Error('protocol refused');};
assert.equal(await blocked.api.openClient(),false);
assert.equal(blocked.elements.get('#clientInstallHelp').hidden,false);
assert.match(blocked.elements.get('#connectionTitle').textContent,/未能发起启动/);
assert.equal(blocked.elements.get('#openClientButton').getAttribute('aria-busy'),'false');

// Advance only the test clock during the explicit user-triggered launch wait.
const timeout=await createSidepanelHarness({contexts:[videoContext()],health:new Error('offline')});
const realSetTimeout=timeout.context.setTimeout;
let clock=Date.now();
timeout.context.Date=class extends Date {static now(){return clock;}};
timeout.context.setTimeout=(callback,ms,...args)=>{
 if(ms===1000){clock+=15000;return realSetTimeout(callback,0,...args);}
 return realSetTimeout(callback,ms,...args);
};
assert.equal(await timeout.api.openClient(),false);
assert.equal(timeout.openedTabs.length,1,'timeout must not relaunch automatically');
assert.equal(timeout.elements.get('#clientInstallHelp').hidden,false);
assert.match(timeout.elements.get('#connectionTitle').textContent,/暂未收到/);
assert.equal(timeout.elements.get('#openClientButton').disabled,false);

let focusAttempts=0;
const restarted=await createSidepanelHarness({contexts:[videoContext()],stored:{pairingTokens:{'http://127.0.0.1:8765':{token:'stale',expiresAt:Date.now()+600000}}},fetchOverride:async(url,options)=>{
 if(!url.endsWith('/api/desktop/focus'))return;
 focusAttempts++;
 if(focusAttempts===1){assert.equal(options.headers['X-LearnNote-Pairing'],'stale');return {ok:false,status:401};}
 assert.equal(options.headers['X-LearnNote-Pairing'],'test-pair');
 return {ok:true,json:async()=>({ok:true,focused:true})};
}});
await restarted.api.openClient();
assert.equal(focusAttempts,2);
assert.equal(restarted.openedTabs.length,0);
console.log('Cold start, bounded wait, native focus, duplicate clicks and launch failure passed');
