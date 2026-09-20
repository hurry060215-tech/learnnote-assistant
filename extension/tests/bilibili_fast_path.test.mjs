import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../background.js',import.meta.url),'utf8');
const reader=source.slice(source.indexOf('async function readBilibiliCaptions('),source.indexOf('const biliSubtitleCache'));
const url='https://www.bilibili.com/video/BV1ABCDEF123/?p=2';
const signed='https://api.bilibili.com/x/player/wbi/v2?aid=123&cid=22&w_rid=fixture';
const calls=[];
const context={URL,AbortController,setTimeout,clearTimeout,location:{href:url},
 __INITIAL_STATE__:{videoData:{bvid:'BV1ABCDEF123',aid:123,pages:[{page:2,cid:22,duration:80}]}},
 performance:{getEntriesByType:()=>[{name:signed},{name:signed.replace('cid=22','cid=99')}]},
 fetch:async (target,options)=>{calls.push({target,credentials:options.credentials});return {ok:true,text:async()=>JSON.stringify(target.includes('/player/')?{code:0,data:{subtitle:{subtitles:[{lan:'zh-CN',subtitle_url:'https://i0.hdslb.com/subtitle.json'}]}}}:{body:[{from:0,to:80,content:'完整字幕'}]})}}};
vm.runInNewContext(reader,context);
const result=await context.readBilibiliCaptions(url);
assert.equal(result.status,'ready');assert.equal(calls.length,2,'current player identity skips view lookup');
assert.equal(calls[0].target,signed,'only the exact part request can be reused');
assert.equal(calls[1].credentials,'omit');

let count=0,release;
const pending=new Promise(resolve=>{release=resolve});
const cacheContext={URL,Date,Map,readBilibiliCaptions(){},captureEpoch:()=>0,captureActive:()=>true,normalizeBrowserSubtitles:x=>x,
 chrome:{scripting:{executeScript:async()=>{count++;await pending;return [{result:{status:'ready',cues:[{start:0,end:80,text:'完整字幕'}],duration:80}}]}}}};
vm.runInNewContext(source.slice(source.indexOf('const biliSubtitleCache'),source.indexOf('async function collectPageData(')),cacheContext);
const first=cacheContext.addBilibiliCaptions({id:1,url},{});
const second=cacheContext.addBilibiliCaptions({id:1,url:url+'&spm_id_from=other'},{});
release();await Promise.all([first,second]);
assert.equal(count,1,'concurrent refresh and send must share one probe');
await cacheContext.addBilibiliCaptions({id:1,url},{});assert.equal(count,1,'ready captions are reused');
await cacheContext.addBilibiliCaptions({id:1,url:url.replace('p=2','p=3')},{});assert.equal(count,2,'different parts never share captions');
console.log('Player identity reuse, signed request matching, credential boundaries and caption request coalescing pass');
