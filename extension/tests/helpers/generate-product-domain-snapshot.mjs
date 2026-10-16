import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { cookiePort, domainSnapshot, fixturePageUrl } from './product-domain-scenarios.mjs';
const root = fileURLToPath(new URL('../../../', import.meta.url));
if (!process.argv.includes('--write')) throw Error('Pass --write to regenerate the original-baseline fixture; full Git history is required.');
const baseline='b590e55169cebd4ca34a7312b16fef1aa3ecec01';
const read = file => execFileSync('git',['show',baseline+':extension/'+file],{cwd:root,encoding:'utf8'});
const background=read('background.js'), content=read('content.js');
function selected(source, indent='') {
  let output='';
  // Original functions are evaluated without startup/event registration.
  const re = new RegExp('^'+indent+'(?:async )?function \\w+\\(', 'gm');
  for(const m of source.matchAll(re)) {
    const end=source.indexOf('\n'+indent+'}\n',m.index)+indent.length+3;
    output+=source.slice(m.index,end)+'\n';
  }
  return output;
}
const common={URL, URLSearchParams, TextEncoder, TextDecoder, Uint8Array, ArrayBuffer, atob, Date};
const bg=vm.createContext({...common, chrome:{cookies:cookiePort()}});
vm.runInContext(read('capture-classification.js'), bg);
vm.runInContext('var {classify, PLAYBACK_ENDPOINT_RE, requestHeaderArrayHasMediaDestination} = globalThis.LearnNoteCaptureClassification;\n'+background.slice(background.indexOf('const MAX_REQUEST_BODY_BYTES'),background.indexOf('function activateCapture'))+'\n'+selected(background),bg);
const dom=vm.createContext({...common, location:{href:fixturePageUrl}});
vm.runInContext(content.slice(0,content.indexOf('const boundVideos'))+'\n'+selected(content),dom);
const data=await domainSnapshot({identity:bg,request:bg,cookies:bg,hints:dom});
writeFileSync(root+'/extension/tests/fixtures/product-domain-snapshot-v1.json',JSON.stringify({baseline,sha256:{background:createHash('sha256').update(background).digest('hex'),content:createHash('sha256').update(content).digest('hex')},snapshot:data},null,2)+'\n');
