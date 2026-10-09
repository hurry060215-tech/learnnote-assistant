import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../desk-events.js', import.meta.url),'utf8');
const {createTaskEventHub} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const connections = [];
let refreshed = 0;
let invalidated = 0;
const hub = createTaskEventHub({connect(url) {
  const listeners = new Map();
  const connection = {url,closed:false,close(){this.closed=true;},addEventListener(name,fn){listeners.set(name,fn);},emit(name,id){listeners.get(name)?.({lastEventId:String(id)});}};
  connections.push(connection);
  return connection;
}, onUpdate:async()=>{refreshed++;}, onInvalidate:()=>{invalidated++;}});
const tasks = [{id:'one',kind:'task',status:'running'}];
hub.sync(tasks);
hub.sync(tasks);
assert.equal(connections.length,1);
connections[0].emit('task_updated',5);
await new Promise(resolve=>setImmediate(resolve));
connections[0].emit('task_updated',5);
connections[0].emit('task_updated',4);
assert.equal(refreshed,1);
hub.sync(tasks,true);
assert(connections[0].closed);
connections[0].emit('task_updated',6);
assert.equal(invalidated,1,'closed stream cannot repaint');
hub.sync(tasks);
assert(connections[1].url.endsWith('after=5'));
connections[1].emit('task_terminal',5);
assert(connections[1].closed,'terminal marker may share the last data ID');
await new Promise(resolve=>setImmediate(resolve));
assert.equal(refreshed,2);
hub.sync(tasks);
connections[2].emit('partial_section_ready',6);
await new Promise(resolve=>setImmediate(resolve));
connections[2].emit('partial_section_ready',6);
assert.equal(refreshed,3,'completed sections refresh once per monotonic cursor');
hub.sync([]);
hub.sync(Array.from({length:10},(_,i)=>({id:'task'+i,kind:'task',status:'running'})));
assert.equal(connections.filter(c=>!c.closed).length,6);
hub.disconnect();
assert(connections.every(c=>c.closed));
console.log('SSE replay deduplication, cursor reconnect, terminal marker and bounded lifecycle pass');

// The real reader cache must be invalidated when a retry is admitted, even
// before task_updated or pipeline_attempt_started arrives from the worker.
const retryConnections = [];
let retryInvalidated = 0;
let retryRefreshed = 0;
const retryHub = createTaskEventHub({
  connect() {
    const listeners = new Map();
    const source = { close() {}, addEventListener(name, fn) { listeners.set(name, fn); },
      emit(name, id) { listeners.get(name)?.({ lastEventId: String(id) }); } };
    retryConnections.push(source);
    return source;
  },
  onInvalidate: id => { assert.equal(id, 'retry'); retryInvalidated++; },
  onUpdate: async () => { retryRefreshed++; },
});
retryHub.sync([{ id: 'retry', kind: 'task', status: 'queued' }]);
retryConnections[0].emit('task_enqueued', 11);
await new Promise(resolve => setImmediate(resolve));
assert.equal(retryInvalidated, 1);
assert.equal(retryRefreshed, 1);
retryConnections[0].emit('task_enqueued', 11);
assert.equal(retryInvalidated, 1, 'replayed admission must be deduplicated');
retryConnections[0].emit('pipeline_attempt_started', 12);
await new Promise(resolve => setImmediate(resolve));
assert.equal(retryInvalidated, 2);
assert.equal(retryRefreshed, 2);
retryHub.disconnect();
console.log('Admission and attempt events invalidate the actual reader event cache');
