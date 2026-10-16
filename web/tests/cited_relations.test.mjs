import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source = readFileSync(new URL('../cited-relations.js', import.meta.url), 'utf8');
const snapshot = () => ({scope:{kind:'library'}, graph:{mode:'local_cited_relations', counts:{scanned_evidence:2,filtered_evidence:2}, warning:'Not truth',nodes:[{id:'a',spellings:['Gradient descent']},{id:'b',spellings:['gradients']}],edges:[{from:'a',to:'b',predicate:'requires',kind:'source_assertion',citations:[{evidence_id:'one',title:'<img onerror=bad()>',locator:'12-18s',quote:'Exact <source>',source:{kind:'task',id:'task-one'},anchors:{start:12,end:18}}, {evidence_id:'two',title:'Document',locator:'paragraph 2',quote:'Exact source',source:{kind:'material',id:'doc-two'},anchors:{page:2}}]}]},evidence:[{evidence_id:'one',text:'Full original <source>'},{evidence_id:'two',text:'Full original second'}]});
function harness(course=null) {
  class Element {
    constructor(tag,text='') {Object.assign(this,{tag,textContent:text,children:[],listeners:{},dataset:{},style:{},value:'',isConnected:true,disabled:false});}
    append(...nodes) {this.children.push(...nodes);}
    replaceChildren(...nodes) {this.children=nodes;}
    setAttribute(key,value){this[key]=value;}
    addEventListener(key,callback){this.listeners[key]=callback;}
    click(){h.downloads.push(this);}
  }
  const h={current:true,requests:[],downloads:[],blobs:[],opened:[],root:new Element('main')};
  const ctx=vm.createContext({document:{createElement:tag=>new Element(tag)},URLSearchParams,Blob,setTimeout:callback=>callback(),URL:{createObjectURL:blob=>{h.blobs.push(blob);return 'blob:local';},revokeObjectURL:()=>{}},literalText:text=>new Element('span',String(text??'')),relationPresentation:edge=>({label:edge.kind}),relationshipGraph:()=>null});
  vm.runInContext(source.replace(/^import .*;$/gm,'').replaceAll('export function','function'),ctx);
  ctx.mountCitedRelations(h.root,{course,isCurrent:()=>h.current,openEvidence:async id=>h.opened.push(id),api:(path,options)=>new Promise((resolve,reject)=>h.requests.push({path,options,resolve,reject}))});
  h.nodes=()=>{const walk=node=>[node,...node.children.flatMap(walk)];return walk(h.root);};
  h.find=predicate=>h.nodes().find(predicate);
  h.submit=()=>h.find(n=>n.tag==='form').listeners.submit({preventDefault(){}});
  h.input=id=>h.find(n=>n.id===id);
  h.button=text=>h.find(n=>n.tag==='button'&&n.textContent===text);
  h.set=(id,value)=>{const input=h.input(id);input.value=value;input.listeners.input();};
  h.flush=()=>new Promise(resolve=>setImmediate(resolve));
  h.query=ctx.relationQuery;return h;
}
{
 const h=harness({id:'a'.repeat(32),revision:4});h.set('relation-q','梯度 & source');h.set('relation-start','12');h.submit();h.submit();
 assert.equal(h.requests.length,1);const u=new URL('http://local'+h.requests[0].path);assert.equal(u.searchParams.get('q'),'梯度 & source');assert.equal(u.searchParams.get('revision'),'4');
 h.requests[0].resolve(snapshot());await h.flush();assert(h.find(n=>n.textContent==='Exact <source>'));assert(!source.includes('innerHTML'));
 await h.button('打开本机出处').listeners.click();assert.deepEqual(h.opened,['one']);
 await h.find(n=>n.dataset.citedRelationExport).listeners.click();assert.deepEqual(JSON.parse(await h.blobs[0].text()),snapshot());
 const selected=h.button('查看涉及此来源的关系').listeners.click();assert.equal(new URL('http://local'+h.requests[1].path).searchParams.get('source_id'),'task-one');
 h.requests[1].resolve(snapshot());await selected;assert(h.find(n=>n.dataset.citedRelationKind));
 h.set('relation-q','changed');assert(!h.find(n=>n.dataset.citedRelationExport));
}
{
 const h=harness();h.submit();h.set('relation-q','new');h.submit();h.requests[1].resolve(snapshot());await h.flush();h.requests[0].resolve({...snapshot(),graph:{...snapshot().graph,warning:'STALE'}});await h.flush();assert(!h.find(n=>n.textContent==='STALE'));
 h.submit();h.current=false;h.requests[2].resolve(snapshot());await h.flush();assert(!h.find(n=>n.dataset.citedRelationExport));
}
{
 const h=harness(),file=h.input('relation-file'),raw=JSON.stringify(snapshot());file.files=[{size:raw.length,text:async()=>raw}];const work=file.listeners.change();await h.flush();
 assert.equal(h.requests[0].path,'/api/concept-relations/preview');assert.equal(h.requests[0].options.body,`{"snapshot":${raw}}`);h.requests[0].resolve({snapshot:snapshot(),warning:'Read only'});await work;
 assert(!h.find(n=>n.dataset.citedRelationOpen));assert(!h.button('查看涉及此来源的关系'));await h.find(n=>n.dataset.citedRelationExport).listeners.click();assert.deepEqual(JSON.parse(await h.blobs[0].text()),snapshot());
 file.files=[{size:20_000_001,text:()=>{throw Error('must not read');}}];await file.listeners.change();assert.equal(h.requests.length,1);assert(!h.find(n=>n.dataset.citedRelationExport));
 file.files=[{size:12,text:async()=>'{"x":1,"x":2}'}];const duplicate=file.listeners.change();await h.flush();assert(h.requests[1].options.body.includes('"x":1,"x":2'));h.requests[1].reject(Error('invalid duplicate'));await duplicate;assert(!h.find(n=>n.dataset.citedRelationExport));
}
{
 const h=harness(),legacy={...snapshot(),schema_version:1};legacy.graph.filters={source_id:'task-one'};legacy.graph.edges=[];
 const raw=JSON.stringify(legacy),file=h.input('relation-file');file.files=[{size:raw.length,text:async()=>raw}];const work=file.listeners.change();await h.flush();
 h.requests[0].resolve({snapshot:legacy,warning:'Read only'});await work;assert(h.find(n=>n.textContent.includes('旧版文件先筛选单个来源')));
 await h.find(n=>n.dataset.citedRelationExport).listeners.click();assert.deepEqual(JSON.parse(await h.blobs[0].text()),legacy);
}
console.log('Cited relation scope, stale responses, literal sources, read-only imports and bounded exports pass');
