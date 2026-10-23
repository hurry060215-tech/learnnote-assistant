import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
const desk = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
const source = readFileSync(new URL("../local-player.js", import.meta.url), "utf8");
const {localMediaSource} = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
const deferred = () => { let resolve; const promise = new Promise(done => resolve = done); return {promise,resolve}; };
function harness({ready=false, changedDigest=false}={}) {
  const old = {kind:"task",id:"child",status:ready?"running":"queued",updated_at:"old",source_media_path:"parent.mp4",
    learning_range:{start:5.25,end:15.75},range_media_ready:ready,media_integrity:{sha256:ready?"clip":""}};
  const next = {...old,status:"running",updated_at:"new",range_media_ready:true,media_integrity:{sha256:changedDigest?"replacement":"clip"}};
  const edition = deferred(), entered = deferred(), calls=[];
  const nodes={sourcePanel:{hidden:false,dataset:{sourceTaskId:"child"}}};
  const state={items:[old],selected:old,epoch:1,lastHealthAt:Date.now(),editing:false};
  const context=vm.createContext({state, localMediaSource, $:id=>nodes[id], syncStatus:{hidden:true},
    api:async route=>route==="/api/tasks/catalog"?{tasks:[next]}:{materials:[]},
    window:{dispatchEvent(){}},CustomEvent:class{},syncTaskEventStreams(){},drawList(){},renderStatus(){},
    claimMapVersion:item=>item.updated_at,claimTimeline:{reset(){}},
    loadEdition:async()=>{entered.resolve();await edition.promise;},openSource:async()=>calls.push(localMediaSource(state.selected))});
  const start=desk.indexOf("async function loadPinnedMaterials("), end=desk.indexOf("async function openItem(",start);
  vm.runInContext(desk.slice(start,end),context);
  return {context,state,nodes,edition,entered,calls};
}
test("same selected queued range opens only its ready clip during summarization",async()=>{
  const h=harness(), pending=h.context.refreshLibrary(); await h.entered.promise; h.edition.resolve(); await pending;
  assert.deepEqual(h.calls,[{id:"child",revision:"clip"}]);
});
test("Close or navigation during queued-to-ready refresh is preserved",async()=>{
  for(const change of [h=>h.nodes.sourcePanel.hidden=true,h=>{h.state.epoch++;h.state.selected={kind:"task",id:"other"};}]){
    const h=harness(),pending=h.context.refreshLibrary();await h.entered.promise;change(h);h.edition.resolve();await pending;
    assert.equal(h.calls.length,0);
  }
});
test("unrelated updated_at changes preserve media; a new digest refreshes it",async()=>{
  for(const changedDigest of [false,true]){
    const h=harness({ready:true,changedDigest}),pending=h.context.refreshLibrary();await h.entered.promise;h.edition.resolve();await pending;
    assert.equal(h.calls.length,changedDigest?1:0);
  }
});
