import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
const nodes=new Map(),storage=new Map();
class Element {
  constructor(){this.value="";this.children=[];this.listeners={};}
  before(){}
  replaceChildren(...children){this.children=children;}
  addEventListener(type,callback){(this.listeners[type]||=[]).push(callback);}
  dispatchEvent(event){for(const fn of this.listeners[event.type]||[])fn(event);}
}
const $=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
$("provider").value="openai";$("baseUrl").value="https://api.openai.com/v1";$("model").value="deepseek-flash";
let response=async()=>({ok:true,model_details:[{id:"deepseek-flash"},{id:"deepseek-v4-pro"}],message:"fixture"});
const context=vm.createContext({Date,document:{getElementById:$,createElement:()=>new Element(),querySelector:()=>new Element()},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},api:(...args)=>response(...args),Event:class{constructor(type){this.type=type;}}});
vm.runInContext(readFileSync(new URL("../desk-model-catalog.js",import.meta.url),"utf8").replace(/^import .*;\r?\n/m,"").replace("export function","function"),context);
context.installModelCatalog({model:{}});
await $("discoverModelList").onclick();assert.equal($("modelChoice").children.length,3);
$("provider").dispatchEvent({type:"change"});assert.equal($("modelChoice").children.length,3,"Reselecting one scope correctly keeps its own cache");
$("provider").value="deepseek";$("baseUrl").value="https://api.deepseek.com";$("provider").dispatchEvent({type:"change"});assert.equal($("modelChoice").children.length,1,"A genuinely different provider/endpoint must have no old options");
let finish;response=()=>new Promise(resolve=>{finish=resolve;});const pending=$("discoverModelList").onclick();
$("provider").value="custom";$("baseUrl").value="https://synthetic.invalid/v1";$("provider").dispatchEvent({type:"change"});finish({ok:true,model_details:[{id:"stale"}]});await pending;
assert.equal($("modelChoice").children.length,1,"A late previous-scope response must not refill the current catalog");
console.log("Catalog cache is isolated by actual provider/endpoint; same-scope cache and stale response behavior are deterministic");
