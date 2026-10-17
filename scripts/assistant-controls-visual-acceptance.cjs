// Real Edge, HTTP, SDK, manifest/queue writes. Only the loopback model replies are synthetic.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'), path=require('node:path'), os=require('node:os'), http=require('node:http');
const {spawn}=require('node:child_process');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,label,timeout=15000){const end=Date.now()+timeout;while(Date.now()<end){if(await check())return;await delay(50);}throw Error(`Timed out: ${label}`);}
(async()=>{
 const out=path.resolve(process.argv[2]||'build/assistant-controls-ui');fs.mkdirSync(out,{recursive:true});
 const data=fs.mkdtempSync(path.join(os.tmpdir(),'learnnote-controls-'));
 const report={ok:false,browser:'Microsoft Edge',model_responses_mocked:true,connection_metadata_mocked:true,actual_api:true,actual_sdk:false,actual_disk:true,errors:[],model_requests:0,executions:0,blocked_requests:[]};
 let browser,backend,fixture,backendFailure,buffer='',dropNext=false;
 const model=http.createServer(async(req,res)=>{try{
  assert.equal(req.method,'POST');assert.equal(req.url,'/v1/chat/completions');assert.match(req.headers['user-agent'],/^OpenAI\/Python/);assert.equal(req.headers.authorization,'Bearer local-no-key');
  let body='';for await(const chunk of req){body+=chunk;assert(body.length<100000);}
  const value=JSON.parse(body),context=JSON.parse(value.messages[1].content);
  assert.equal(context.source.kind,'course');assert.equal(context.source.id,fixture.control_course_id);
  assert.deepEqual(value.tools.map(t=>t.function.name).sort(),['inspect_course','set_course_paused']);
  assert.equal(context.untrusted_selected_status,undefined);assert.equal(context.untrusted_selected_note_text,undefined);
  assert.equal(value.max_tokens,3000);assert.equal(value.parallel_tool_calls,false);report.actual_sdk=true;report.model_requests++;
  res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({id:'synthetic-control-plan',object:'chat.completion',created:0,model:'mocked-acceptance-model',choices:[{index:0,finish_reason:'tool_calls',message:{role:'assistant',content:null,tool_calls:[{id:'synthetic-call',type:'function',function:{name:'set_course_paused',arguments:'{"paused":true}'}}]}}]}));
 }catch(error){report.errors.push(error.message);res.writeHead(500);res.end('Synthetic model contract failure');}});
 try{
  await new Promise(resolve=>model.listen(0,'127.0.0.1',resolve));const modelBase=`http://127.0.0.1:${model.address().port}/v1`;
  const env={};for(const[key,value]of Object.entries(process.env))if(/^(PATH|SYSTEMROOT|WINDIR|COMSPEC|PATHEXT|TEMP|TMP|LANG|LC_ALL)$/i.test(key))env[key]=value;
  Object.assign(env,{PYTHONUTF8:'1',PYTHONUNBUFFERED:'1',PYTHONDONTWRITEBYTECODE:'1'});
  backend=spawn(process.env.LEARNNOTE_ACCEPTANCE_PYTHON||'python',[path.join(__dirname,'assistant-runs-fixture.py'),'--data-dir',data,'--model-base',modelBase,'--controls','--startup-report',path.join(out,'controls-startup.json')],{cwd:path.resolve(__dirname,'..'),env,stdio:['ignore','pipe','pipe']});
  backend.on('error',error=>backendFailure=error);backend.on('exit',code=>backendFailure=Error(`Fixture exited ${code}`));
  for(const stream of[backend.stdout,backend.stderr])stream.on('data',chunk=>{fs.appendFileSync(path.join(out,'backend.log'),chunk);buffer+=chunk.toString();for(const line of buffer.split(/\r?\n/)){if(line.startsWith('{"fixture_origin":'))fixture=JSON.parse(line);}});
  await until(async()=>{if(backendFailure)throw backendFailure;if(!fixture)return false;try{return(await fetch(fixture.fixture_origin+'/health')).ok;}catch{return false;}},'fixture health',60000);
  const base=fixture.fixture_origin,coursePath=path.join(data,'courses',fixture.control_course_id+'.json'),taskPath=path.join(data,'tasks',fixture.control_task_id,'task.json'),originalPath=path.join(data,'tasks',fixture.control_task_id,'original.txt');
  const course=()=>JSON.parse(fs.readFileSync(coursePath,'utf8')),task=()=>JSON.parse(fs.readFileSync(taskPath,'utf8')),original=fs.readFileSync(originalPath);
  browser=await chromium.launch({channel:'msedge',headless:true});const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce',serviceWorkers:'block'});
  await context.route('**/*',async route=>{const req=route.request(),url=new URL(req.url());
   if(url.origin!==base){report.blocked_requests.push(url.origin);return route.abort('blockedbyclient');}
   if(url.pathname==='/api/model/connection')return route.fulfill({json:{model:{provider:'custom',base_url:modelBase,model:'mocked-acceptance-model',use_saved_connection:false},configured:true,storage:'none'}});
   if(req.method()==='POST'&&/\/api\/assistant\/operations\/[^/]+\/execute$/.test(url.pathname)){
    report.executions++;if(dropNext){dropNext=false;const response=await route.fetch();assert(response.ok());report.lost_real_response=(await response.json()).status==='completed';await response.dispose();return route.abort('failed');}
   }return route.continue();
  });
  const p=await context.newPage();p.on('pageerror',error=>report.errors.push(error.message));await p.goto(base);await p.locator('#aiAssistant').click();await p.locator('#assistantOperations').click();
  const dialog=()=>p.locator('#assistantOperationsDialog'),card=()=>dialog().locator('[data-agent-card]');
  async function select(kind,id){await dialog().locator('[data-agent-domain]').selectOption(kind);await dialog().locator(`[data-agent-target] option[value="${id}"]`).waitFor({state:'attached'});await dialog().locator('[data-agent-target]').selectOption(id);await p.waitForFunction(()=>document.querySelector('[data-agent-target-status]').textContent.includes('版本')||document.querySelector('[data-agent-target-status]').textContent.includes('轮次'));}
  async function preview(tool,args={}){await dialog().locator('[name=tool]').selectOption(tool);for(const[name,value]of Object.entries(args))await dialog().locator(`[name=${name}]`).selectOption(value);await dialog().locator('[data-agent-local] button[type=submit]').click();await card().locator('[data-agent-apply]').waitFor();}
  async function ready(){await p.waitForFunction(()=>!document.querySelector('[data-agent-plan]').disabled);}
  async function apply(expected='已完成'){await card().locator('[data-agent-apply]').click();await p.waitForFunction(text=>document.querySelector('[data-agent-card] h3')?.textContent.includes(text),expected);await ready();}
  await select('course',fixture.control_course_id);await preview('inspect_course');await apply();assert.match(await card().innerText(),/Synthetic control course/);
  await dialog().locator('details').first().locator('summary').click();await dialog().locator('[data-agent-question]').fill('Pause this explicitly selected course.');assert.equal(await dialog().locator('[data-agent-share]').isChecked(),false);
  await dialog().locator('[data-agent-plan]').click();await card().locator('[data-agent-apply]').waitFor();assert.equal(course().paused,false);await apply();assert.equal(course().paused,true);assert.equal(report.model_requests,1);
  report.structured_plan_confirmed=true;report.before_confirmation_unchanged=true;
  await dialog().locator('[data-agent-target-refresh]').click();await p.waitForFunction(()=>document.querySelector('[data-agent-target-status]').textContent.includes('版本 2'));
  await preview('set_course_paused',{paused:'false'});const before=course();const changed=await p.request.put(base+'/api/courses/'+fixture.control_course_id,{data:{title:'Manual synthetic title',sources:before.sources,paused:true,revision:before.revision}});assert(changed.ok());await apply('存在冲突');assert.equal(course().paused,true);assert.equal(course().title,'Manual synthetic title');report.stale_confirmation_preserved_manual_change=true;
  await dialog().locator('[data-agent-target-refresh]').click();await p.waitForFunction(()=>document.querySelector('[data-agent-target-status]').textContent.includes('版本 3'));await preview('set_course_paused',{paused:'false'});
  const executions=report.executions;dropNext=true;await card().locator('[data-agent-apply]').click();await until(()=>report.lost_real_response,'actual execution response loss');await ready();assert.equal(course().paused,false);
  await card().getByRole('button',{name:'刷新实际状态',exact:true}).click();await p.waitForFunction(()=>document.querySelector('[data-agent-card] h3')?.textContent.includes('已完成'));assert.equal(report.executions,executions+1);report.recovery_did_not_repeat_write=true;
  const latest=course();const manualPause=await p.request.put(base+'/api/courses/'+fixture.control_course_id,{data:{title:latest.title,sources:latest.sources,paused:true,revision:latest.revision}});assert(manualPause.ok());
  await card().getByRole('button',{name:'刷新实际状态',exact:true}).click();await until(async()=>/最新读取的课程状态：已暂停后续准备，课程版本 5/.test(await card().innerText()),'course refreshed observation');assert.match(await card().innerText(),/这次操作已恢复.*课程版本 4/);report.history_and_current_course_state_distinguished=true;
  await dialog().locator('[data-agent-target-refresh]').click();await p.waitForFunction(()=>document.querySelector('[data-agent-target-status]').textContent.includes('版本 5'));await preview('set_course_paused',{paused:'false'});await card().locator('[data-agent-cancel]').click();await p.waitForFunction(()=>document.querySelector('[data-agent-card] h3')?.textContent.includes('已取消'));assert.equal(course().paused,true);report.cancelled_preview_no_write=true;
  await select('task_control',fixture.control_task_id);await preview('inspect_task');await apply();assert.equal(task().cancel_requested,false);await preview('cancel_task');assert.equal(task().status,'running');await apply();
  await until(()=>task().status==='cancelled','real worker acknowledgement');await until(async()=>{await card().getByRole('button',{name:'刷新实际状态',exact:true}).click();return /执行回调结束：已确认/.test(await card().innerText());},'real queue callback completion');
  assert.match(await card().innerText(),/执行器确认取消：是/);assert.equal(await card().locator('[data-agent-undo]').count(),0);assert.deepEqual(fs.readFileSync(originalPath),original);
  report.actual_worker_cancelled=true;report.original_bytes_preserved=true;report.no_undo_for_cancel=true;
  assert.doesNotMatch(await dialog().locator('[data-agent-status]').innerText(),/撤销/);report.no_undo_promise_for_controls=true;
  await p.screenshot({path:path.join(out,'desktop-controls.png')});await p.setViewportSize({width:390,height:844});await p.screenshot({path:path.join(out,'mobile-controls.png')});assert(await dialog().evaluate(el=>el.getBoundingClientRect().width<=390));report.narrow_width=390;
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.blocked_requests,[]);report.ok=true;
 }catch(error){report.errors.push(error.stack||error.message);process.exitCode=1;}
 finally{
  if(browser)await browser.close();if(backend&&backend.exitCode===null){backend.kill();await Promise.race([new Promise(resolve=>backend.once('exit',resolve)),delay(5000)]);if(backend.exitCode===null&&backend.signalCode===null){backend.kill('SIGKILL');await new Promise(resolve=>backend.once('exit',resolve));}}
  await new Promise(resolve=>model.close(resolve));fs.rmSync(data,{recursive:true,force:true});report.temporary_data_removed=!fs.existsSync(data);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));
 }
})();
