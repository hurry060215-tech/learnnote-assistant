const assert = require('node:assert/strict');
const { installRouteGate } = require('../local-player-route-gate.cjs');
const deferred = () => { let resolve; const promise = new Promise(done => resolve = done); return {promise,resolve}; };
async function fixture(options = {}) {
  const errors = [], canceled = [];
  const page = { removed:0, async route(pattern,handler) { this.handler=handler; },
    async unroute(pattern,handler) { assert.equal(handler,this.handler); this.removed++; } };
  const gate = await installRouteGate(page,'synthetic',{label:'synthetic',onError:error=>errors.push(error),onCanceled:error=>canceled.push(error),...options});
  return {page,gate,errors,canceled};
}
(async () => {
  const f = await fixture(), continued=deferred(), settled=deferred(); let calls=0;
  const request={failure:()=>null};
  const running=f.page.handler({request:()=>request,continue:async()=>{calls++;continued.resolve();await settled.promise;}});
  await f.gate.waitReached();
  const first=f.gate.finish(), second=f.gate.finish(); assert.equal(first,second);
  await continued.promise; assert.equal(f.page.removed,0,'Do not unregister an unsettled request');
  settled.resolve(); await first; await running;
  assert.equal(calls,1); assert.equal(f.page.removed,1); assert.deepEqual(f.errors,[]);

  const canceled=await fixture({allowCanceled:true}); let canceledCalls=0;
  const canceledWork=canceled.page.handler({request:()=>({failure:()=>({errorText:'net::ERR_ABORTED'})}),
    continue:async()=>{canceledCalls++;throw new Error('Route is already handled!');}});
  await canceled.gate.waitReached(); await canceled.gate.finish(); await canceledWork;
  assert.equal(canceledCalls,1); assert.deepEqual(canceled.errors,[]); assert.deepEqual(canceled.canceled,['net::ERR_ABORTED']);

  const connection=await fixture({allowCanceled:true});
  const connectionWork=connection.page.handler({request:()=>({failure:()=>({errorText:'net::ERR_CONNECTION_REFUSED'})}),
    continue:async()=>{throw new Error('connection failed');}});
  await connection.gate.waitReached(); await assert.rejects(connection.gate.finish(),/connection failed/); await connectionWork;
  assert.equal(connection.errors.length,1); assert.deepEqual(connection.canceled,[]);

  for (const message of ['Route is already handled!','Target page, context or browser has been closed']) {
    const broken=await fixture(); let attempts=0;
    const work=broken.page.handler({request:()=>({failure:()=>null}),continue:async()=>{attempts++;throw new Error(message);}});
    await broken.gate.waitReached(); await assert.rejects(broken.gate.finish(),error=>error.message===message); await work;
    assert.equal(attempts,1); assert.equal(broken.errors.length,1,'Rejected handlers must be recorded, not escape as unhandled promises');
  }
  const preparation=await fixture({prepare:async()=>{throw new Error('real HTTP fetch failed');}});
  await preparation.page.handler({request:()=>({failure:()=>null})});
  await assert.rejects(preparation.gate.waitReached(),/real HTTP fetch failed/);
  await assert.rejects(preparation.gate.finish(),/real HTTP fetch failed/);
  assert.equal(preparation.errors.length,1);
  console.log('Delayed route ownership, release, confirmed cancellation, unexpected rejection and browser teardown pass');
})().catch(error=>{console.error(error);process.exitCode=1;});
