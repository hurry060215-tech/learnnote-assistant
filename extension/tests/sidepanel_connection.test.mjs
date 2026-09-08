import assert from 'node:assert/strict';
import {createSidepanelHarness,videoContext} from './sidepanel_test_harness.mjs';
const live={service:'learnnote',app_version:'0.2.3',backend_version:'0.2.3',protocol_version:1};
const h=await createSidepanelHarness({contexts:[videoContext()],tabs:[{id:15,url:'http://127.0.0.1:18898/#task/demo'}],healthByUrl:{'http://127.0.0.1:18898/health':live}});
assert.equal(h.api.getState().backendUrl,'http://127.0.0.1:18898');
assert.equal(h.api.getState().clientConnected,true);
const unrelated=await createSidepanelHarness({contexts:[videoContext()],health:{ok:true}});
assert.equal(unrelated.api.getState().clientConnected,false);
console.log('Discovers an existing workbench on another port and rejects unrelated local services');
