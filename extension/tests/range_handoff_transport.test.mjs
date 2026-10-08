import { installExtensionScriptLoader } from "./helpers/script-loader.mjs";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
const hooks={},listener=name=>({addListener(fn){if(name)hooks[name]=fn;}});
const env={console,URL,Date,setTimeout,clearTimeout,chrome:{permissions:{contains:async()=>true},webRequest:Object.fromEntries(["onBeforeSendHeaders","onHeadersReceived","onBeforeRedirect","onCompleted","onErrorOccurred"].map(k=>[k,listener()])),tabs:{onRemoved:listener(),onActivated:listener(),onUpdated:listener(),get:async id=>({id,url:"https://www.bilibili.com/video/BV1xx?p=2"})},action:{onClicked:listener()},runtime:{onMessage:listener("message"),sendMessage:async()=>({})},sidePanel:{},scripting:{}}};
vm.createContext(env);installExtensionScriptLoader(env);vm.runInContext(await readFile(new URL("../background.js",import.meta.url),"utf8"),env);
vm.runInContext('activateCapture=()=>{}; mergeAndRankResources=()=>[]; postJsonWithRetry=async(url,payload)=>({task_id:"fixture",payload});',env);
const send=message=>new Promise(resolve=>hooks.message(message,{},resolve));
const base={type:"start-current-task",targetTabId:5,mode:"subtitle_only",handoffId:"synthetic-range",page:{page_url:"https://www.bilibili.com/video/BV1xx?p=2",title:"Original",browser_subtitles:[{start:10,end:20,text:"Original"}]},options:{content_mode:"subtitles"}};
for(const range of [{start:10,end:20},{},undefined]){
 const result=await send({...base,learning_range:range});
 assert(result.payload,JSON.stringify(result));
 assert.deepEqual(JSON.parse(JSON.stringify(result.payload.learning_range)),range || {});
 assert.equal(result.payload.cookies.length,0);assert.equal(result.payload.page_url,base.page.page_url);
}
console.log("Range survives actual background handoff transport; whole-video remains an empty object and subtitle capture reads no cookies");
