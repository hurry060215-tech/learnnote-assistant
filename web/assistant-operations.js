import { api } from "/web/desk-api.js";

const endpoint = "/api/assistant/operations";
const title = { read_note: "读取保存正文", edit_note: "编辑个人修订", export_note: "生成导出文件", update_reading: "调整阅读外观", inspect_task: "读取任务状态", cancel_task: "请求取消当前轮任务", inspect_course: "读取课程状态", set_course_paused: "设置课程暂停状态" };
const controlTools = new Set(["inspect_task", "cancel_task", "inspect_course", "set_course_paused"]);
const uid = () => crypto.randomUUID();
const labels={theme:"主题",size:"字号",font:"字体",width:"正文宽度",leading:"行距",weight:"字重",density:"密度",accent:"强调色"};
const names={light:"浅色",dark:"深色",sans:"无衬线",serif:"衬线",mono:"等宽",comfortable:"舒适",compact:"紧凑",neutral:"中性",teal:"青绿",blue:"蓝色",plum:"紫色",markdown:"Markdown",html:"HTML",docx:"Word",pdf:"PDF"};
const display=value=>names[value]||String(value??"—");
function operationText(value){
  if(controlTools.has(value.tool)){
    const observed=value.result?.observation||value.preview?.before||{};
    if(value.tool==="set_course_paused"){
      if(!value.result)return `后续分集准备：${observed.paused?"已暂停":"允许准备"} → ${value.arguments?.paused??value.preview?.arguments?.paused?"暂停":"允许准备"}。`;
      let text=`这次操作已${value.result.paused?"暂停":"恢复"}后续分集准备，课程版本 ${value.result.revision}。已有任务保持原状，本次没有启动新任务。`;
      if(value.result.observation)text+=`\n最新读取的课程状态：${observed.paused?"已暂停后续准备":"允许后续准备"}，课程版本 ${observed.revision}。`;
      return text;
    }
    if(value.tool==="inspect_course")return `课程：${observed.title||"所选课程"}\n版本：${observed.revision}\n后续分集准备：${observed.paused?"已暂停":"允许准备"}\n来源 ${observed.source_count} 项，分集 ${observed.episode_count} 项\n${Object.entries(observed.status_counts||{}).map(([key,count])=>`${key}：${count}`).join("\n")}`;
    let text=`本次读取的任务轮次：${String(observed.generation||"").slice(0,12)}\n观测到的任务状态：${observed.status||"尚未读取"}`;
    if(value.result?.historical_request)text+=`\n这次历史取消请求：${value.result.historical_request.recorded?"已记录":"未确认"}，轮次 ${String(value.result.historical_request.generation||"").slice(0,12)}`;
    text+=`\n当前轮次取消请求：${observed.cancellation_requested?"已提出":"未提出"}\n排队执行被阻止：${observed.queued_job_cancelled?"是":"未确认"}\n执行器确认取消：${observed.worker_acknowledged?"是":"未确认"}\n执行回调结束：${observed.callback_finished===true?"已确认":observed.callback_finished===false?"未结束或没有启动":"暂无可靠记录"}`;
    if(observed.dispatch_prevented)text+="\n调度器已确认本轮未进入队列。";
    if(observed.recovery_stopped)text+="\n重启恢复已确认原执行器不再活动；不代表原回调正常结束。";
    return text;
  }
  if(value.client){
    const after=value.status==="prepared"?{...value.before,...value.arguments}:value.after;
    const changes=Object.keys(labels).filter(key=>value.before?.[key]!==after?.[key]);
    let text=changes.map(key=>`${labels[key]}：${display(value.before?.[key])} → ${display(after?.[key])}`).join("\n")||"阅读外观保持当前设置。";
    if(value.replayed)text+="\n\n以上为这次操作的历史结果。当前设置：\n"+Object.keys(labels).map(key=>`${labels[key]}：${display(value.current?.[key])}`).join("\n");
    return text;
  }
  if(value.preview?.diff)return value.preview.diff;
  if(value.result?.text!==undefined)return value.result.text;
  const args=value.preview?.arguments||{};
  if(value.tool==="read_note")return `从第 ${args.start_line||1} 行开始，最多读取 ${args.line_count||100} 行。`;
  if(value.tool==="export_note")return value.result?`文件已生成，大小 ${value.result.bytes} 字节。请使用下方链接下载。\n${(value.result.warnings||[]).join("\n")}`:`生成 ${display(args.format)} 文件；使用当前保存版本。`;
  if(value.tool==="edit_note"&&args.text)return `${{replace:"精确替换一处",append:"追加段落",set_title:"修改正文标题"}[args.mode]||"编辑正文"}\n${args.old_text?"原文："+args.old_text+"\n":""}新文字：${args.text}`;
  if(value.result?.revision)return value.result.changed===false?"正文内容保持不变。":"已保存个人修订，可在正文中核对。";
  return "请核对下方操作状态。";
}

export function installAssistantOperations(ctx) {
  const { state, openItem, options, notice } = ctx;
  const launch = document.createElement("button");
  launch.type = "button"; launch.id = "assistantOperations"; launch.textContent = "操作软件";
  document.querySelector("#assistantPanel header > div").prepend(launch);
  const dialog = document.createElement("dialog");
  dialog.id = "assistantOperationsDialog"; dialog.className = "tools-dialog";
  dialog.setAttribute("aria-labelledby", "assistantOperationsTitle");
  dialog.innerHTML = `<header><h2 id="assistantOperationsTitle">操作软件</h2><button type="button" data-agent-close aria-label="关闭操作软件">×</button></header>
    <p data-agent-source class="muted"></p><p>助手可实际读取、编辑、导出保存正文，调整阅读外观，读取任务或课程状态，以及请求取消任务、设置课程暂停。一次执行一个已确认操作；正文与外观编辑支持撤销。</p>
    <label>操作对象<select data-agent-domain><option value="note">当前保存正文与阅读外观</option><option value="task_control">一个现有任务</option><option value="course">一个现有课程</option></select></label>
    <div data-agent-control-target hidden><label>明确选择对象<select data-agent-target></select></label><button type="button" data-agent-target-refresh>重新读取对象状态</button><p data-agent-target-status class="muted"></p></div>
    <details><summary>用自然语言安排操作</summary><label>希望完成什么<textarea data-agent-question maxlength="1000" rows="3" placeholder="例如：把当前笔记的正文标题改为 学习率笔记"></textarea></label>
    <label class="check"><input type="checkbox" data-agent-share>本次允许当前文字模型读取所选正文或任务/课程的有限状态</label>
    <p class="muted">提交会把这条要求、所选对象标识，以及笔记操作时的阅读设置发送给当前所选模型，可能产生用量费用。默认不发送正文或状态明细；没有后台会话日志上传。</p>
    <button type="button" data-agent-plan>生成操作预览</button></details>
    <form data-agent-local><label>本地操作（无需模型）<select name="tool"><option value="read_note">读取保存正文</option><option value="edit_note">编辑个人修订</option><option value="export_note">生成导出文件</option><option value="update_reading">调整阅读外观</option></select></label>
    <div data-agent-fields></div><button class="primary" type="submit">预览操作</button></form>
    <p data-agent-status role="status"></p><section data-agent-card aria-live="polite"></section>
    <details><summary>最近执行记录（保存在本机，包含读取正文与撤销副本）</summary><button type="button" data-agent-history>刷新记录</button><div data-agent-records></div></details>`;
  document.body.append(dialog);
  const $ = selector => dialog.querySelector(selector);
  let epoch = 0, active = null, busy = false, request = null, clientExecution = null, selectedControl = null;
  const reading = () => window.LearnNoteReadingSettings;
  const dirty = () => state.editing && document.getElementById("noteText").value !== state.text;
  const source = () => {
    if($("[data-agent-domain]").value!=="note"){
      if(!selectedControl)throw new Error("请先明确选择任务或课程，并读取它的当前状态。");
      return {...selectedControl};
    }
    if (!state.selected || !state.revision) throw new Error("请先打开一份已保存的笔记或资料。");
    if (dirty()) throw new Error("当前正文有未保存修改，请先保存或保留草稿，再安排操作。");
    return { kind: state.selected.kind, id: state.selected.id, revision: state.revision };
  };
  function assertCurrent(value) {
    const selected = value.source ? source() : null;
    if (selected && ["kind", "id", "revision"].some(key=>selected[key]!==value.source[key]))
      throw new Error("当前来源或版本已变化，请重新预览；没有改动其他笔记。");
  }
  function status(message) { $("[data-agent-status]").textContent = message; }
  function invalidate(){epoch++;active=null;selectedControl=null;request?.abort();request=null;$("[data-agent-share]").checked=false;$("[data-agent-card]").replaceChildren();}
  async function loadControl(){
    const kind=$("[data-agent-domain]").value,id=$("[data-agent-target]").value,token=epoch;
    selectedControl=null;if(kind==="note"||!id)return;
    try{
      const result=await api(`${endpoint}/targets/${kind}/${encodeURIComponent(id)}`);
      if(token!==epoch||!dialog.open)return;
      selectedControl=result.source;
      $("[data-agent-target-status]").textContent=kind==="course"?`课程版本 ${result.source.revision}；${result.observation.paused?"已暂停后续准备":"允许后续准备"}`:`当前任务轮次 ${result.source.revision.slice(0,12)}；状态 ${result.observation.status}`;
    }catch(error){if(token===epoch)status(error.message);}
  }
  async function changeDomain(){
    invalidate();const kind=$("[data-agent-domain]").value,token=epoch;
    $("[data-agent-source]").textContent=kind==="note"?(state.selected?`当前来源：${state.selected.title}（已保存版本）`:"未选择来源；可调整阅读外观。"):(kind==="course"?"操作范围：下面明确选择的一门课程。":"操作范围：下面明确选择的一个任务及其当前轮次。");
    $("[data-agent-control-target]").hidden=kind==="note";
    const tool=$("[name=tool]");tool.replaceChildren();
    const allowed=kind==="course"?["inspect_course","set_course_paused"]:kind==="task_control"?["inspect_task","cancel_task"]:["read_note","edit_note","export_note","update_reading"];
    for(const name of allowed){const option=document.createElement("option");option.value=name;option.textContent=title[name];tool.append(option);}fields();
    if(kind==="note")return;
    const target=$("[data-agent-target]");target.replaceChildren();
    const empty=document.createElement("option");empty.value="";empty.textContent="请选择，不会自动执行";target.append(empty);
    try{
      const data=await api(`${endpoint}/targets?kind=${kind}`);if(token!==epoch||!dialog.open)return;
      for(const item of data.targets){const option=document.createElement("option");option.value=item.id;option.textContent=`${item.title} · ${item.id}`;target.append(option);}
      $("[data-agent-target-status]").textContent=data.truncated?"仅显示前 200 项；请确认所选对象。":"请先明确选择对象。";
    }catch(error){if(token===epoch)status(error.message);}
  }
  $("[data-agent-domain]").onchange=changeDomain;
  $("[data-agent-target]").onchange=()=>{invalidate();return loadControl();};
  $("[data-agent-target-refresh]").onclick=()=>{invalidate();return loadControl();};
  async function run(work) {
    if (busy) return;
    busy = true; const token = epoch;
    for (const button of dialog.querySelectorAll("button")) if (!button.hasAttribute("data-agent-close") && !button.hasAttribute("data-agent-cancel")) button.disabled = true;
    try { await work(() => dialog.open && token === epoch); }
    catch (error) { if (dialog.open && token === epoch) status(error.name === "AbortError" ? "已停止等待；实际执行状态请查看本机记录。" : error.message); }
    finally { busy = false; if (dialog.open) for (const button of dialog.querySelectorAll("button")) button.disabled = false; }
  }
  function fields() {
    const tool = $("[name=tool]").value;
    if(controlTools.has(tool)){
      $("[data-agent-fields]").innerHTML=tool==="set_course_paused"?'<label>明确设置<select name="paused"><option value="true">暂停后续分集准备</option><option value="false">恢复后续分集准备</option></select></label><p class="muted">已有任务不受影响。恢复不会自动开始下载、转写或模型调用。</p>':tool==="cancel_task"?'<p class="muted">只取消所选的当前一轮，保留现有文件。取消无法撤销；请求成功不等于执行已经停止。</p>':'<p class="muted">只读本机有限状态；不读取正文或调用模型。</p>';
      return;
    }
    $("[data-agent-fields]").innerHTML = tool === "read_note" ? '<div class="appearance-grid"><label>起始行<input name="start_line" type="number" min="1" max="100000" value="1"></label><label>读取行数<input name="line_count" type="number" min="1" max="200" value="100"></label></div>'
      : tool === "export_note" ? '<label>格式<select name="format"><option value="markdown">Markdown</option><option value="docx">Word</option><option value="pdf">PDF</option><option value="html">HTML</option></select></label>'
      : tool === "edit_note" ? '<label>编辑方式<select name="mode"><option value="replace">精确替换一处</option><option value="append">追加段落</option><option value="set_title">修改正文一级标题</option></select></label><label data-agent-old>原文字串<textarea name="old_text" rows="3" maxlength="20000"></textarea></label><label>新文字<textarea name="text" rows="4" maxlength="20000" required></textarea></label><p class="muted">只保存个人修订，原文件保留；撤销副本含前后正文，仅保存在本机。</p>'
      : '<div class="appearance-grid">' + Object.entries({theme:["主题",["light","dark"]],size:["字号",[15,16,17,18,20]],font:["字体",["sans","serif","mono"]],width:["正文宽度",["760","940","1120"]],leading:["行距",["1.65","1.85","2.1"]],weight:["字重",["400","500","600"]],density:["密度",["comfortable","compact"]],accent:["强调色",["neutral","teal","blue","plum"]]}).map(([key,[label,values]])=>`<label>${label}<select name="${key}"><option value="">保持当前</option>${values.map(value=>`<option value="${value}">${display(value)}</option>`).join("")}</select></label>`).join("") + '</div>';
    const mode = $("[name=mode]");
    if (mode) { mode.onchange = () => { $("[data-agent-old]").hidden = mode.value !== "replace"; }; mode.onchange(); }
  }
  $("[name=tool]").onchange = fields; fields();
  function localArguments(tool) {
    const value = name => $(`[name=${name}]`)?.value || "";
    if(controlTools.has(tool))return tool==="set_course_paused"?{paused:value("paused")==="true"}:{};
    if (tool === "read_note") return { start_line: Number(value("start_line")), line_count: Number(value("line_count")) };
    if (tool === "export_note") return { format: value("format") };
    if (tool === "edit_note") return { mode: value("mode"), text: value("text"), old_text: value("mode") === "replace" ? value("old_text") : "" };
    return Object.fromEntries(["theme","size","font","width","leading","weight","density","accent"].filter(key=>value(key)).map(key=>[key,key==="size"?Number(value(key)):value(key)]));
  }
  async function prepare(candidate, current) {
    assertCurrent(candidate);
    if (candidate.tool === "update_reading") {
      const snapshot = reading()?.read();
      if (!snapshot?.ok) throw new Error(snapshot?.error || "本设备阅读设置暂不可用。");
      if (!Object.keys(candidate.arguments).length) throw new Error("请至少选择一项阅读设置。");
      active = {...candidate, id:uid(), client:true, expectedRevision:snapshot.revision, before:snapshot.settings, status:"prepared"};
    } else {
      active = await api(`${endpoint}/prepare`, {method:"POST",body:JSON.stringify({operation_id:uid(),...candidate})});
    }
    if (current()) render(active);
  }
  function render(value) {
    active = value;
    const card = $("[data-agent-card]"); card.replaceChildren();
    const heading = document.createElement("h3"); heading.textContent = `${title[value.tool] || "阅读外观"} · ${{prepared:"待执行",running:"执行中",completed:"已完成",cancelled:"已取消",conflict:"存在冲突",failed:"未完成"}[value.status] || value.status}`; card.append(heading);
    if(value.source){const label=document.createElement("p");const item=state.items?.find(item=>item.id===value.source.id&&item.kind===value.source.kind);label.textContent=`操作对象：${item?.title||value.source.id} · 版本 ${String(value.source.revision).slice(0,12)}`;card.append(label);}
    const pre = document.createElement("pre");
    pre.textContent = operationText(value);
    card.append(pre);
    if(value.tool==="read_note"&&value.result){const scope=document.createElement("p");scope.textContent=`本次从第 ${value.result.start_line} 行读取 ${value.result.line_count} 行，正文共 ${value.result.total_lines} 行。`+(value.result.truncated?"显示达到本次字数上限，末尾已截断；请缩小行数继续读取。":"");card.append(scope);}
    if (value.receipt_warning) { const warning=document.createElement("p");warning.textContent=value.receipt_warning;card.append(warning); }
    if (value.error) { const text=document.createElement("p");text.textContent=typeof value.error==="string"?value.error:JSON.stringify(value.error);card.append(text); }
    if (value.preview?.notice) { const text=document.createElement("p");text.textContent=value.preview.notice;card.append(text); }
    const button = (label, action, key) => { const item=document.createElement("button");item.type="button";item.textContent=label;if(key)item.dataset[key]="";item.disabled=busy&&key!=="agentCancel";item.onclick=action;card.append(item);return item; };
    if (value.status === "prepared") button("执行此操作",()=>run(async current=>{
      assertCurrent(value); status("正在执行，结果将保存在本机…");
      if (value.client) {
        clientExecution=new AbortController();
        let receipt;
        try{receipt=await reading().patch({operationId:value.id,expectedRevision:value.expectedRevision,patch:value.arguments,signal:clientExecution.signal});}
        finally{clientExecution=null;}
        if(current())render({...value,...receipt,status:receipt.ok?"completed":receipt.status});
        if (!receipt.ok) throw new Error(receipt.error?.message || receipt.error || "阅读设置未能保存，请先刷新核对实际记录。");
      } else {
        const result=await api(`${endpoint}/${value.id}/execute`,{method:"POST",body:JSON.stringify({confirm:true})});
        if(current())render(result);
        if(current()&&result.status==="completed"&&result.tool==="edit_note"&&!dirty()&&state.selected?.id===result.source.id&&state.selected?.kind===result.source.kind)await openItem(state.selected);
      }
      if(current())status("执行结果已更新；可查看正文、文件或撤销。");
    }),"agentApply");
    if (["prepared","running"].includes(value.status)) button("取消操作",async()=>{
      const token=epoch;const stillCurrent=()=>dialog.open&&epoch===token&&active?.id===value.id;
      try { if(value.client&&clientExecution){clientExecution.abort();status("已请求取消，正在核对是否已提交。");return;}const result=value.client?{...value,status:"cancelled"}:await api(`${endpoint}/${value.id}/cancel`,{method:"POST"});if(stillCurrent())render(result); }
      catch(error){if(stillCurrent())status(error.message);}
    },"agentCancel");
    if(value.status==="completed"&&!value.undo_of&&!value.undone_by&&!value.targetOperationId&&(value.client||value.tool==="edit_note"))button("撤销这次修改",()=>run(async current=>{
      if(!value.client&&(dirty()||state.selected?.id!==value.source.id||state.selected?.kind!==value.source.kind))throw new Error("请先打开这份来源并处理未保存的草稿，再撤销正文修改。");
      value.undoId ||= uid();
      value.undoRevision ||= value.client?reading().read().revision:"";
      const result=value.client?await reading().undo({operationId:value.undoId,targetOperationId:value.id,expectedRevision:value.undoRevision}):await api(`${endpoint}/${value.id}/undo`,{method:"POST",body:JSON.stringify({operation_id:value.undoId})});
      if(value.client&&!result.ok)throw new Error(result.error?.message||result.error||"无法撤销。");
      if(current())render(value.client?{...result,id:result.operationId,client:true,tool:"update_reading",status:"completed"}:result);
      if(current()&&!value.client&&result.status==="completed"&&!dirty()&&state.selected?.id===result.source.id&&state.selected?.kind===result.source.kind)await openItem(state.selected);
    }),"agentUndo");
    if(value.status==="completed"&&value.tool==="export_note"){
      const link=document.createElement("a");link.className="tool-link";link.href=`${endpoint}/${value.id}/artifact`;link.download="";link.textContent="下载已生成文件";card.append(link);
    }
    if(!value.client&&["completed","cancelled","failed","conflict","unavailable"].includes(value.status))button("删除此操作记录…",()=>{
      if(!window.confirm("删除这次操作及关联撤销记录、正文副本和导出缓存？这不会撤销已执行的操作，此后不能用这条记录撤销。"))return;
      run(async current=>{await api(`${endpoint}/${value.id}`,{method:"DELETE",body:JSON.stringify({confirm:true})});if(current()){active=null;card.replaceChildren();status("操作记录与关联副本已删除，当前正文未变化。");}});
    });
    button("刷新实际状态",()=>run(async current=>{
      const result=value.client?reading().operation(value.id):await api(`${endpoint}/${value.id}`);
      if(controlTools.has(value.tool)&&result?.result){
        const latest=await api(`${endpoint}/targets/${value.source.kind}/${encodeURIComponent(value.source.id)}`);
        result.result={...result.result,observation:latest.observation};
      }
      if(current()&&result){if(value.client&&!result.ok)throw new Error(result.error?.message||"尚无已提交的本机记录。");render(value.client?{...value,...result,status:"completed"}:result);}
    }));
  }
  $("[data-agent-local]").onsubmit = event => {event.preventDefault();run(async current=>{
    const tool=$("[name=tool]").value;
    await prepare({tool,arguments:localArguments(tool),...(tool==="update_reading"?{}:{source:source()})},current);
    if(current())status("请检查操作内容，然后执行。");
  });};
  $("[data-agent-plan]").onclick=()=>run(async current=>{
    const question=$("[data-agent-question]").value.trim();if(!question)throw new Error("请填写要完成的操作。");
    const domain=$("[data-agent-domain]").value;
    const selected=domain!=="note"||state.selected?source():null, snapshot=domain==="note"?reading()?.read():null;
    const safeReading=snapshot?.ok?Object.fromEntries(Object.entries(snapshot.settings).filter(([key])=>["theme","size","font","width","leading","weight","density","accent"].includes(key))):null;
    request=new AbortController();status("当前模型正在选择受支持的工具，尚未执行修改…");
    const result=await api(`${endpoint}/plan`,{method:"POST",signal:request.signal,body:JSON.stringify({question,source:selected,reading:safeReading,share_source:$("[data-agent-share]").checked,options:options()})});
    if(!current())return;
    if(result.state!=="proposed"){status("未执行操作。"+result.answer);return;}
    await prepare({tool:result.tool,arguments:result.arguments,...(result.source?{source:result.source}:{})},current);
    if(current())status(`已生成工具操作预览；本次模型读取所选内容 ${result.shared_characters} 字。执行前请核对。`);
  });
  $("[data-agent-history]").onclick=()=>run(async current=>{
    const data=await api(endpoint);if(!current())return;const panel=$("[data-agent-records]");panel.replaceChildren();
    const local=reading()?.recentOperations?.();
    if(local&&!local.ok)throw new Error(local.error?.message||local.error||"阅读设置历史暂不可读，请保留现有数据并稍后重试。");
    const records=[...(data.operations||[]),...(local?.operations||[]).map(value=>({...value,id:value.operationId,client:true,tool:"update_reading",status:"completed"}))];
    for(const value of records){const button=document.createElement("button");button.type="button";button.textContent=`${title[value.tool]||"操作"} · ${value.status} · ${(value.updated_at||"").slice(0,19)}`;button.onclick=()=>render(value);panel.append(button);}
    if(!records.length)panel.textContent="还没有执行记录。";
  });
  launch.onclick=()=>{
    epoch++;active=null;status(busy?"上一操作仍在处理，完成后可刷新实际执行记录。":"");$("[data-agent-card]").replaceChildren();
    $("[data-agent-domain]").value="note";changeDomain();
    $("[data-agent-question]").value=document.getElementById("aiQuestion").value;
    $("[data-agent-share]").checked=false;dialog.showModal();
  };
  $("[data-agent-close]").onclick=()=>dialog.close();
  dialog.addEventListener("click",event=>{if(event.target===dialog){const bounds=dialog.getBoundingClientRect();if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)dialog.close();}});
  dialog.addEventListener("close",()=>{epoch++;request?.abort();request=null;if(busy)notice("执行状态保存在本机；重新打开操作记录可核对结果。");});
}
