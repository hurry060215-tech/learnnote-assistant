import assert from "node:assert/strict";
import fs from "node:fs";
const source = fs.readFileSync(new URL("../material-ocr.js", import.meta.url), "utf8");
const { canOcrMaterial, mountMaterialOcr } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
class Element {
  constructor(tag) { this.tagName=tag; this.children=[]; this.dataset={}; this.listeners={}; this.attributes={}; this._text=""; this.disabled=false; }
  get isConnected() { return this.tagName === "body" || Boolean(this.parent?.isConnected); }
  get textContent() { return this._text + this.children.map(child=>child.textContent).join(""); }
  set textContent(value) { this._text=String(value); this.replaceChildren(); }
  append(...items) { for(const item of items){item.parent=this;this.children.push(item);} }
  prepend(item) { item.parent=this;this.children.unshift(item); }
  replaceChildren(...items) { for(const child of this.children) child.parent=null; this.children=[];this.append(...items); }
  setAttribute(key,value) { this.attributes[key]=value; }
  addEventListener(name,fn) { this.listeners[name]=fn; }
  async click() { if (!this.disabled) await this.listeners.click?.(); }
}
const all = root => [root, ...root.children.flatMap(all)];
const byTag = (root,tag) => all(root).filter(element=>element.tagName===tag);
const fixture = {status:"partial",page_count:3,processed_page_count:2,warning:"已完成 2 / 3 页；未核验",pages:[
  {page:1,confidence:0.82,lines:[{text:"Synthetic OCR <img onerror=bad>",confidence:0.92},{text:"Unscored line",confidence:null}]},
  {page:2,confidence:null,text:"",lines:[]},
]};
const material = {kind:"material",id:"synthetic-pdf",source_type:"pdf",status:"ocr_partial",metadata:{ocr_performed:true}};
function setup(handler=async()=>({ocr:structuredClone(fixture)}), isCurrent=()=>true) {
  const body=new Element("body"),container=new Element("main");body.append(container);
  globalThis.document={createElement:tag=>new Element(tag)};
  globalThis.confirm=()=>true;
  const calls=[],updates=[];
  const panel=mountMaterialOcr(container,{material,api:async(...args)=>{calls.push(args);return handler(...args);},isCurrent,onUpdated:async(value)=>updates.push(value)});
  return {body,container,calls,updates,...panel};
}
assert.equal(canOcrMaterial({...material,status:"ready"}),true);
assert.equal(canOcrMaterial({...material,status:"ocr_required",metadata:{}}),true);
assert.equal(canOcrMaterial({...material,status:"ready",metadata:{}}),false);
assert.equal(canOcrMaterial({...material,source_type:"txt"}),false);
{
 const h=setup();await h.ready;
 assert.equal(h.calls.length,1);assert.equal(h.calls[0][1],undefined,"Opening saved confidence must only read");
 assert.match(h.root.textContent,/识别器平均置信度 82% · 未核验/);
 assert.match(h.root.textContent,/识别器平均置信度 未知 · 未核验/);
 assert.match(h.root.textContent,/继续识别未完成页面/);
 const details=byTag(h.root,"details");details[0].open=true;details[0].listeners.toggle();
 assert.match(details[0].textContent,/Synthetic OCR <img onerror=bad>/,"Recognition is literal text, not executable HTML");
 assert.match(details[0].textContent,/识别器置信度 92% · 未核验/);
 assert.match(details[0].textContent,/识别器置信度 未知 · 未核验/);
 const count=details[0].children.length;details[0].listeners.toggle();assert.equal(details[0].children.length,count);
 details[1].open=true;details[1].listeners.toggle();assert.match(details[1].textContent,/本页未识别到文字/);
}
{
 let resolve,posts=0;
 const h=setup(async(path,options)=>options?.method==="POST"?(posts++,await new Promise(done=>resolve=done)):{ocr:structuredClone(fixture)});
 await h.ready;const button=byTag(h.root,"button")[0];
 globalThis.confirm=()=>false;await button.click();assert.equal(posts,0,"Cancel cannot start recognition");
 globalThis.confirm=()=>true;const running=button.click();await button.click();assert.equal(posts,1,"Repeated clicks cannot duplicate a batch");
 resolve({ocr:{...fixture,status:"ready",warning:"已完成 3 页；未核验"},material:{...material,status:"ready"}});await running;
 assert.equal(button.hidden,true);assert.equal(h.updates.length,1);
}
{
 let fail=true;
 const h=setup(async(path,options)=>{if(options?.method==="POST"&&fail)throw new Error("Synthetic OCR unavailable");return {ocr:structuredClone(fixture),material};});
 await h.ready;const button=byTag(h.root,"button")[0];await button.click();
 assert.match(h.root.textContent,/Synthetic OCR unavailable.*已保存的 OCR 结果仍保留/s);
 assert.equal(byTag(h.root,"details").length,2);assert.equal(button.disabled,false);assert.equal(h.updates.length,0);
 fail=false;await button.click();assert.equal(h.updates.length,1,"A failed batch stays retryable");
}
{
 let resolve,current=true;
 const h=setup(async()=>await new Promise(done=>resolve=done),()=>current);
 current=false;resolve({ocr:fixture});await h.ready;
 assert.equal(byTag(h.root,"details").length,0,"A late cache read cannot repaint a newer selection");
}
{
 let resolve,current=true;
 const h=setup(async(path,options)=>options?.method==="POST"?await new Promise(done=>resolve=done):{ocr:structuredClone(fixture)},()=>current);
 await h.ready;const button=byTag(h.root,"button")[0],running=button.click();
 current=false;h.container.replaceChildren();resolve({ocr:{...fixture,status:"ready"},material});await running;
 assert.equal(h.updates.length,0,"Close, navigation or editing cannot reopen or refresh a stale panel");
 assert.equal(h.container.children.length,0);
}
console.log("PDF OCR cache confidence, continuation, retry, repeated clicks, cancel and navigation are safe");
