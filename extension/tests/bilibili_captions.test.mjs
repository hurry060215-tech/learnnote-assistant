import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../background.js',import.meta.url),'utf8');
const code=source.slice(source.indexOf('async function readBilibiliCaptions('),source.indexOf('const biliSubtitleCache'));
async function run({login=false,part=2,foreign=false,switchPage=false,videoId="BV1ABCDEF123",fallback=false}={}) {
 const urls=[];const credentials=[];const href=`https://www.bilibili.com/video/${videoId}?p=${part}`;const ctx={URL,AbortController,setTimeout,clearTimeout,location:{href},fetch:async(url,options)=>{urls.push(url);credentials.push(options.credentials);let body;
 if(url.includes('web-interface/view'))body={code:0,data:{pages:[{page:1,cid:11,duration:10},{page:2,cid:22,duration:20}]}};
 else if(url.includes('/player/'))body={code:fallback && url.includes('/wbi/')?-403:0,data:{need_login_subtitle:login,subtitle:{subtitles:login?[]:[{lan:'en',subtitle_url:'https://i0.hdslb.com/en.json'},{lan:'ai-zh',subtitle_url:foreign?'https://evil.example/sub.json':'https://i0.hdslb.com/cn.json'}]}}};
 else {body={body:[{from:0,to:10,content:'完整字幕'}]};if(switchPage)ctx.location.href=href.replace('p=2','p=1');}
 return {ok:true,text:async()=>JSON.stringify(body)};}};vm.runInNewContext(code,ctx);return {result:await ctx.readBilibiliCaptions(href),urls,credentials};
}
const ready=await run();assert.equal(ready.result.status,'ready');assert(ready.urls[1].endsWith('cid=22'));assert(ready.urls[2].endsWith('/cn.json'));assert.equal(ready.credentials[2],'omit');assert.equal(ready.result.cues.length,1);
assert.equal((await run({login:true})).result.status,'auth_required');assert.equal((await run({foreign:true})).result.status,'untrusted_subtitle_host');assert.equal((await run({switchPage:true})).result.status,'source_changed');assert.equal((await run({part:3})).result.status,'unavailable');console.log('Bilibili caption click fetch: exact part, Chinese preference, login, domain and SPA boundaries pass');

const av=await run({videoId:"av117233128837493"});assert.equal(av.result.status,"ready");assert(av.urls[0].includes("aid=117233128837493"));assert(av.urls[1].includes("aid=117233128837493"));assert.equal((await run({fallback:true})).result.status,"ready");
