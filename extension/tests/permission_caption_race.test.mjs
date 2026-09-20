import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../background.js', import.meta.url), 'utf8');
const tab = {id: 7, url: 'https://www.bilibili.com/video/BV1ABCDEF123?p=1'};
let epoch = 0, active = true, calls = 0;
const pending = [];
const context = {URL, Date, Map, readBilibiliCaptions(){},
  captureEpoch: () => epoch, captureActive: () => active,
  normalizeBrowserSubtitles: value => value,
  normalizePermissionOrigin: value => value,
  resourceByTab: new Map(), pageStateByTab: new Map(),
  activeCaptureUntilByTab: {delete(){active = false;}},
  clearCaptureLog(){epoch++;},
  chrome: {tabs: {query: async () => [tab]}, scripting: {executeScript(){
    calls++;
    return new Promise(resolve => pending.push(resolve));
  }}}
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('const biliSubtitleCache'), source.indexOf('async function collectPageData(')), context);
vm.runInContext(source.slice(source.indexOf('async function revokeSitePermissionCaches('), source.indexOf('chrome.permissions?.onRemoved')), context);
const response = text => [{result:{status:'ready', cues:[{start:0,end:10,text}],duration:10}}];
const old = context.addBilibiliCaptions(tab, {});
await context.revokeSitePermissionCaches('https://www.bilibili.com/*');
active = true;
const fresh = context.addBilibiliCaptions(tab, {});
assert.equal(calls, 2);
pending[0](response('revoked old captions'));
assert.equal((await old).browser_subtitles, undefined);
const coalesced = context.addBilibiliCaptions(tab, {});
assert.equal(calls, 2, 'old completion must not remove the new pending request');
pending[1](response('new grant captions'));
assert.equal((await fresh).browser_subtitles[0].text, 'new grant captions');
await coalesced;
await context.revokeSitePermissionCaches('https://www.bilibili.com/*');
active = true;
const again = context.addBilibiliCaptions(tab, {});
assert.equal(calls, 3, 'revocation must also clear already completed subtitle cache');
pending[2](response('third grant'));
await again;
console.log('Permission revocation clears completed captions and rejects in-flight stale captions');
