import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../platform-signals.js',import.meta.url),'utf8');
const context=vm.createContext({URL});
for(const key of ['document','window','localStorage','fetch','chrome']) Object.defineProperty(context,key,{get(){throw new Error(`Pure platform domain touched ${key}`);}});
vm.runInContext(readFileSync(new URL('../task-format.js',import.meta.url),'utf8'),context);
vm.runInContext(source,context);
const module=context.LearnNotePlatformSignals;
assert(Object.isFrozen(module));
assert.equal(module.platformSignalSiteName({page_url:"https://example.test/watch"}),"example.test");
const fixture=JSON.parse(readFileSync(new URL('./fixtures/platform-signals-e4ab6f1.json',import.meta.url),'utf8'));
for(const row of fixture){
 const before=JSON.stringify(row.input);
 assert.deepEqual(JSON.parse(JSON.stringify(module.platformSignalProfile(row.input))),row.profile);
 assert.deepEqual(JSON.parse(JSON.stringify(module.platformHeaderNames(row.input))),row.headers);
 assert.equal(module.platformSignalHtml(row.input),row.html);
 assert.equal(module.chaoxingProfileHtml(row.input),row.html);
 assert.equal(JSON.stringify(row.input),before);
}
assert(!/\beval\s*\(|\bFunction\s*\(/.test(source));
assert.equal(module.platformSignalHtml({selected_resource:{kind:'video',request_header_names:['Authorization','Cookie','Referer']}}).includes('Authorization'),false);
console.log(`Platform evidence domain preserves ${fixture.length} frozen profile/header/HTML outputs, has no browser effects and does not mutate tasks`);
