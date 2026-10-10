import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../screen-subtitles.js", import.meta.url), "utf8");
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => { resolve=a; reject=b; }); return {promise,resolve,reject}; };
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness() {
  class Element {
    constructor() { this.isConnected=true; this.children=[]; this.style={}; this.disabled=false; this.hidden=false; this.listeners={}; this.value=""; this.checked=false; this.html=""; }
    set innerHTML(value) { this.html=value; }
    get innerHTML() { return this.html; }
    addEventListener(name,fn) { this.listeners[name]=fn; }
    replaceChildren(...children) { this.html="";this.children=children; }
    prepend(child) { this.children.unshift(child); }
    reportValidity() { return true; }
  }
  const selectors = ["form", "[data-screen-preview]", "[data-screen-result]", "[data-start-screen]", "[data-preview-screen]", "[data-refresh-screen]", "[data-resume-screen]", "[data-cancel-screen]"];
  const nodes=new Map(selectors.map(key=>[key,new Element()]));
  const values={cropLeft:0,cropTop:74,cropRight:100,cropBottom:100,interval:.5,language:"auto",previewTime:0,generateNote:false};
  const fields=Object.fromEntries(Object.entries(values).map(([key,value])=>[key,Object.assign(new Element(),{value:String(value),checked:false})]));
  const form=nodes.get("form");form.elements={namedItem:name=>fields[name]};
  const root=new Element();root.querySelector=selector=>nodes.get(selector);root.querySelectorAll=()=>selectors.filter(key=>key.includes("screen]" )&&!key.includes("result")&&!key.includes("preview]" )).map(key=>nodes.get(key));
  const h={root,nodes,fields,form,current:true,calls:[],posts:[],opens:[],refreshes:0,messages:[]};
  const context=vm.createContext({document:{createElement:()=>new Element()},esc:value=>String(value??"").replaceAll("<","&lt;").replaceAll(">","&gt;"),timestamp:value=>String(value)});
  vm.runInContext(source.replace(/^import .*;\r?\n/,"").replaceAll("export function","function").replaceAll("export async function","async function"),context);
  h.context=context;
  h.ready=context.mountScreenSubtitles(root,{source:{id:"source/id",kind:"task"},options:()=>({content_mode:"text"}),isCurrent:()=>h.current,
    status:value=>h.messages.push(value),refresh:async()=>{h.refreshes++;},openTask:async result=>{h.opens.push(result);},
    api:async(path,options)=>{h.calls.push({path,options});if(options?.method==="POST"){const work=deferred();h.posts.push(work);return work.promise;}
      return path.endsWith("screen-subtitles")?{status:"not_started"}:{task:{mode:"local",status:"success"}};}});
  h.submit=()=>form.onsubmit({preventDefault(){},stopPropagation(){}});
  h.preview=()=>nodes.get("[data-preview-screen]").onclick();
  return h;
}
{
  const h=harness();await h.ready;
  assert.equal(h.calls.length,2,"Opening only reads saved results and status");
  const settings=h.context.screenSubtitleSettings(h.form);
  assert.equal(settings.crop_top,.74);assert.equal(settings.language,"auto");
  h.fields.cropTop.value="100";
  assert.throws(()=>h.context.screenSubtitleSettings(h.form),/裁剪范围/);
}
{
  const h=harness();await h.ready;
  h.submit();h.submit();await tick();
  assert.equal(h.posts.length,1,"Double submit starts only one task");
  const sent=JSON.parse(h.calls.at(-1).options.body);
  assert.equal(sent.generate_note,false);assert.equal(sent.options,null);
  assert.equal(h.calls.at(-1).path,"/api/tasks/source%2Fid/screen-subtitles");
  h.posts[0].resolve({task_id:"separate-result"});await tick();
  assert.equal(h.opens.length,1);assert.equal(h.refreshes,1);
}
{
  const h=harness();await h.ready;
  h.fields.generateNote.checked=true;h.form.listeners.input();h.submit();await tick();
  assert.match(h.nodes.get("[data-start-screen]").textContent,/并生成笔记/);
  const sent=JSON.parse(h.calls.at(-1).options.body);
  assert.equal(sent.generate_note,true);assert.equal(sent.options.content_mode,"text");
  h.current=false;h.posts[0].resolve({task_id:"created-after-close"});await tick();
  assert.equal(h.opens.length,0,"Finishing after Close cannot reopen or replace a new view");
  assert.equal(h.refreshes,1,"Created task remains discoverable even after Close");
}
{
  const h=harness();await h.ready;const work=h.preview();await tick();
  h.fields.cropTop.value="60";h.form.listeners.input();
  h.posts[0].resolve({warning:"stale",lines:[{text:"OLD CROP",selected:true,confidence:.9}]});await work;
  assert.equal(h.nodes.get("[data-screen-preview]").innerHTML,"","Edited settings invalidate an older crop preview");
}
{
  const h=harness();await h.ready;const work=h.preview();await tick();
  h.current=false;h.posts[0].reject(new Error("late error"));await work;
  assert.equal(h.messages.length,0,"Closed or navigated panel does not show stale errors");
}
{
  const h=harness();await h.ready;
  const html=h.context.screenSubtitleResultHtml({status:"partial",warning:"OCR <script>",coverage:{sampled_seconds:60,requested_seconds:130},cues:[{start:0,end:1,text:"<img onerror=x>",confidence:.7,lines:[]}],failed_windows:[{}]});
  assert.match(html,/仅有部分覆盖/);assert.match(html,/不能作为完整字幕笔记/);
  assert(!html.includes("<script>"));assert(!html.includes("<img onerror=x>"));
  assert.match(html,/70%/);
}
console.log("Screen-subtitle settings, explicit model opt-in, duplicate clicks, Close/navigation and stale crop previews passed");
