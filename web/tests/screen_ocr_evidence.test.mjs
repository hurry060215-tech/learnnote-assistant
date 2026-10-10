import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
const source=readFileSync(new URL('../desk.js',import.meta.url),'utf8');
const start=source.indexOf('  if (t.claim_evidence');
const end=source.indexOf('  panel.dataset.status',start);
assert(start>=0&&end>start);
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.listeners={};this.open=false;this.textContent='';}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  addEventListener(name,fn){this.listeners[name]=fn;}
}
const all=node=>[node,...node.children.flatMap(all)];
for (const mode of ['screen_subtitles','local']) {
  const panel=new Element('section');
  const t={id:'fixture',kind:'task',mode,claim_evidence:{path:'claim_evidence_map.json',quality:{claim_count:2,direct_count:1,located_only_count:1}}};
  const evidence=[{evidence_id:'match',kind:'transcript',locator:'1.0-2.0s',...(mode==='screen_subtitles'?{source:'screen-ocr',verification:'unreviewed'}:{})}];
  const mapped={claims:[{text:'<literal OCR>',claim_type:'transcript',verification:'direct',evidence_ids:['match']},{text:'possibly',claim_type:'unsupported',verification:'located_only',candidate_evidence_ids:['match']}],evidence};
  const opens=[];
  const context=vm.createContext({t,panel,document:{createElement:tag=>new Element(tag)},api:async()=>mapped,openEvidenceSource:async(...args)=>opens.push(args),failure:()=>{}});
  vm.runInContext(source.slice(start,end),context);
  const details=all(panel).find(node=>node.tag==='details');details.open=true;
  await details.listeners.toggle();
  const labels=all(panel).filter(node=>node.tag==='span').map(node=>node.textContent);
  if(mode==='screen_subtitles') {
    assert.equal(labels[0],'逐字匹配 · 画面字幕 OCR · 未人工核验 · <literal OCR>');
    assert.match(labels[1],/仅定位 · 画面字幕 OCR · 未人工核验/);
    assert.match(all(panel).find(node=>node.tag==='summary').textContent,/OCR 未人工核验/);
  } else assert.match(labels[0],/直接支持 · 字幕/);
  const button=all(panel).find(node=>node.tag==='button');
  if(mode==='screen_subtitles') assert.match(button.textContent,/OCR（未核验）/);
  await button.onclick();
  assert.equal(opens.length,1);assert.equal(opens[0][1],1);
}
console.log('OCR direct matches stay labeled unreviewed; candidate links identify OCR and preserve navigation');
