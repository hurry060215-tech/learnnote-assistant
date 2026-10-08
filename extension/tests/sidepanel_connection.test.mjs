import assert from 'node:assert/strict';
import {createSidepanelHarness,videoContext} from './sidepanel_test_harness.mjs';
const live={service:'learnnote',app_version:'0.2.3',backend_version:'0.2.3',protocol_version:1};
const h=await createSidepanelHarness({contexts:[videoContext()],tabs:[{id:15,url:'http://127.0.0.1:18898/#task/demo'}],healthByUrl:{'http://127.0.0.1:18898/health':live}});
assert.equal(h.api.getState().backendUrl,'http://127.0.0.1:18898');
assert.equal(h.api.getState().clientConnected,true);
const unrelated=await createSidepanelHarness({contexts:[videoContext()],health:{ok:true}});
assert.equal(unrelated.api.getState().clientConnected,false);
const incompatible=await createSidepanelHarness({
  contexts:[videoContext()],
  healthByUrl:{'http://127.0.0.1:8765/health':{service:'learnnote',app_version:'0.1.0',backend_version:'0.1.0',protocol_version:2}}
});
assert.equal(incompatible.api.getState().clientConnected,false);
assert.equal(incompatible.elements.get('#connectionTitle').textContent,'扩展与客户端协议不兼容');
assert.match(incompatible.elements.get('#connectionDetail').textContent,/扩展协议 1；本机 LearnNote 0\.1\.0 使用协议 2/);
assert.equal(incompatible.elements.get('#clientInstallHelp').hidden,false);
incompatible.elements.get('#connectionTitle').textContent='previous status';
await incompatible.api.checkClient({quiet:true});
assert.equal(incompatible.elements.get('#connectionTitle').textContent,'扩展与客户端协议不兼容');
console.log('Discovers a paired workbench, rejects unrelated services, and explains protocol mismatches');
