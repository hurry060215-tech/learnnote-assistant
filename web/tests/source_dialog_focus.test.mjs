import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

function harness() {
  const pending = [], document = { activeElement: null };
  class Element {
    constructor(tag) { this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.isConnected=true; }
    append(...nodes) { for(const node of nodes){node.parent=this;this.children.push(node);} }
    addEventListener(name, callback) { this.listeners[name]=callback; }
    contains(node) { return node===this || this.children.some(child=>child.contains(node)); }
    focus() { document.activeElement=this; }
    showModal() { this.open=true;this.focus(); }
    close() { this.open=false;document.activeElement=document.body;pending.push(()=>this.listeners.close?.()); }
    remove() { this.isConnected=false;this.parent.children=this.parent.children.filter(node=>node!==this); }
  }
  document.body=new Element("body");document.createElement=tag=>new Element(tag);
  const context=vm.createContext({document});vm.runInContext(readFileSync(new URL("../learning.js",import.meta.url),"utf8"),context);
  return { document, Element, open: context.LearnNoteLearning.openEvidence, flush:()=>pending.splice(0).forEach(fn=>fn()) };
}
for(const moveFocusBeforeCloseEvent of [false,true]){
  const h=harness(),source=new h.Element("button"),remembered=new h.Element("button");source.focus();
  await h.open({id:"synthetic-evidence",apiUrl:x=>x,fetchJson:async()=>({evidence:{title:"Synthetic",locator:"paragraph 1",text:"Original text"}})});
  const dialog=h.document.body.children[0];dialog.close();
  if(moveFocusBeforeCloseEvent)remembered.focus();
  h.flush();
  assert.equal(h.document.activeElement,moveFocusBeforeCloseEvent?remembered:source,"Delayed close must not steal focus from a newer keyboard target");
  assert.equal(dialog.isConnected,false);
}
console.log("Source dialog restores ordinary focus but preserves a newer keyboard target across delayed close events");
