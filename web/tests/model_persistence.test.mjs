import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";

const connections = fs.readFileSync(new URL("../desk-connections.js", import.meta.url), "utf8")
  .replace(/^import .*;\r?\n/m, "").replace(/export /g, "");
const desk = fs.readFileSync(new URL("../desk.js", import.meta.url), "utf8");
const submit = desk.slice(desk.indexOf('$("settingsForm").onsubmit ='), desk.indexOf('$("theme").onclick'));
const model = {provider:"xiaomi",base_url:"https://api.xiaomimimo.com/v1",model:"mimo-test",use_saved_connection:true};

function harness(api) {
  const nodes = new Map();
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, {value:"",dataset:{},disabled:false,close(){}});
    return nodes.get(id);
  };
  let marked = 0;
  const stored = new Map();
  const context = vm.createContext({api, $, state:{model:{...model},key:"",modelConnectionReady:true},
    document:{getElementById:$}, localStorage:{setItem:(key,value)=>stored.set(key,value)},
    window:{dispatchEvent(){},LearnNoteSettings:{modelSaved(){marked++;return true;},updateDirty(){}}},
    CustomEvent:class {}, notice(){},
  });
  vm.runInContext(connections,context);
  vm.runInContext(submit,context);
  $("provider").value="xiaomi";$("baseUrl").value=model.base_url;$("model").value=model.model;
  return {context,$,stored,marked:()=>marked};
}

test("a fresh browser restores the server-selected provider without receiving a key",async()=>{
  const h=harness(async()=>({model:{...model},configured:true,storage:"system",message:"saved"}));
  h.context.state.model={provider:"kimi"};
  await h.context.loadModelConnection(h.context.state);
  assert.equal(h.context.state.model.provider,"xiaomi");
  assert.equal(h.context.state.modelConnectionReady,true);
  assert.equal(h.context.state.key,"");
  assert.equal(JSON.parse(h.stored.get("learnnote.desk.model")).use_saved_connection,true);
  assert(!h.stored.get("learnnote.desk.model").includes("api_key"));
});

test("clearing the shared model removes stale saved selection in another page",async()=>{
  const h=harness(async()=>({model:null,configured:false,storage:"none",message:"cleared"}));
  await h.context.loadModelConnection(h.context.state);
  assert.equal(Object.keys(h.context.state.model).length,0);
  assert.equal(h.context.state.modelConnectionReady,false);
  assert.equal(h.context.state.key,"");
});

test("a delayed restore does not replace a newer save or unsaved model editing",async()=>{
  let finish;
  const h=harness(()=>new Promise(resolve=>{finish=resolve;}));
  const pending=h.context.loadModelConnection(h.context.state);
  h.context.state.modelSaveEpoch=1;h.context.state.model={provider:"new-provider"};
  finish({model:{...model},configured:true});await pending;
  assert.equal(h.context.state.model.provider,"new-provider");
  const another=h.context.loadModelConnection(h.context.state);
  h.$("settingsDialog").dataset.unsaved="true";
  finish({model:{...model},configured:true});await another;
  assert.equal(h.context.state.model.provider,"new-provider");
});

test("failed server save keeps the current connection and the entered replacement",async()=>{
  const h=harness(async()=>{throw new Error("test service unavailable");});
  h.$("apiKey").value="replacement-test-key";h.$("model").value="new-model";
  await h.$("settingsForm").onsubmit({preventDefault(){}});
  assert.equal(h.context.state.model.model,"mimo-test");
  assert.equal(h.$("apiKey").value,"replacement-test-key");
  assert.match(h.$("settingsStatus").textContent,/未能保存/);
  assert.equal(h.marked(),0);assert.equal(h.$("savePreferences").disabled,false);
});

test("model save reuses only the exact endpoint and retains typing during a delayed response",async()=>{
  let finish,payload;
  const h=harness((url,options)=>{payload=JSON.parse(options.body);return new Promise(resolve=>{finish=resolve;});});
  h.$("model").value="saved-model";
  const pending=h.$("settingsForm").onsubmit({preventDefault(){}});
  assert.equal(payload.use_saved_connection,true);assert.equal(payload.api_key,"");
  h.$("model").value="new-unsaved-model";
  finish({model:{...model,model:"saved-model"},configured:true,storage:"system",message:"saved"});
  await pending;
  assert.equal(h.context.state.model.model,"saved-model");
  assert.equal(h.$("model").value,"new-unsaved-model");
  assert.equal(h.marked(),0);assert.match(h.$("settingsStatus").textContent,/尚未保存/);
  h.$("baseUrl").value=model.base_url+"/different";
  const other=h.$("settingsForm").onsubmit({preventDefault(){}});
  assert.equal(payload.use_saved_connection,false);
  finish({model:{...model,base_url:payload.base_url},configured:false,message:"missing key"});await other;
});
