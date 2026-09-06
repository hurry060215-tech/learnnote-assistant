/* Local course organization and quoted comparisons. No generated facts. */
(() => {
  let activeCourseId = "";
  async function open({apiUrl, fetchJson, currentSource, navigate, createTask, onEvidence}) {
    const previous = document.activeElement;
    const dialog = document.createElement("dialog"); dialog.className = "course-dialog";
    const heading = document.createElement("h2"); heading.textContent = "课程与引用对照";
    const status = document.createElement("p"); status.setAttribute("role", "status");
    const body = document.createElement("div");
    const select = document.createElement("select"); select.setAttribute("aria-label", "选择课程");
    let course = null, busy = false, navigationGeneration = 0;
    const button = (label, handler) => {
      const element = document.createElement("button"); element.type = "button"; element.textContent = label;
      element.onclick = async () => { try { await handler(); } catch(error) { status.textContent = error.message || "操作失败，请重试。"; } };
      return element;
    };
    const close = button("关闭", () => dialog.close());
    dialog.addEventListener("close", () => { dialog.remove(); previous?.focus?.(); });
    const courseTitle = document.createElement("input"); courseTitle.placeholder = "新课程名称"; courseTitle.setAttribute("aria-label", "新课程名称"); courseTitle.maxLength = 200;
    const createGroup=document.createElement('details');createGroup.className='course-new';const createSummary=document.createElement('summary');createSummary.textContent='新建课程';
    const create = button("创建课程", async () => {
      const generation=++navigationGeneration;body.textContent="正在创建课程…";
      const result = await fetchJson(apiUrl("/api/courses"), {method:"POST", headers:{"Content-Type":"application/json"},body:JSON.stringify({title:courseTitle.value,sources:[]})});
      if(generation!==navigationGeneration||!dialog.isConnected)return;
      courseTitle.value=""; await loadOptions(result.course.id);
      createGroup.open=false;
    });
    async function loadOptions(selected = activeCourseId || select.value) {
      const generation=++navigationGeneration;body.textContent="正在读取课程…";
      const result = await fetchJson(apiUrl("/api/courses"));if(generation!==navigationGeneration||!dialog.isConnected)return;select.replaceChildren();
      for (const item of result.courses) { const option = document.createElement("option"); option.value=item.id; option.textContent=item.title; select.append(option); }
      if(!result.courses.length)createGroup.open=true;
      if ([...select.options].some(option=>option.value===selected)) select.value=selected;
      activeCourseId = select.value;
      await loadCourse();
    }
    async function loadCourse() {
      if (!select.value) { body.textContent="创建课程后，可以加入当前资料、调整阅读顺序或粘贴多个视频链接。"; course=null;return; }
      const generation=++navigationGeneration,id=select.value;body.textContent="正在读取课程…";
      const result=await fetchJson(apiUrl(`/api/courses/${id}`));if(generation!==navigationGeneration||!dialog.isConnected)return;
      course=result.course;render();
    }
    async function save() {
      const {id,title,sources,paused,revision}=course;
      const result=await fetchJson(apiUrl(`/api/courses/${id}`),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({title,sources,paused,revision})});
      if(select.value!==id||!dialog.isConnected)return;course=result.course;
      render();
    }
    function render() {
      body.replaceChildren();
      const title=document.createElement("h3");title.textContent=course.title;
      const tools=document.createElement("div");tools.className="course-tools";
      tools.append(button("加入当前资料",async()=>{const source=currentSource();if(!source){status.textContent="请先在资料库中打开一份视频或文档。";return}course.sources.push(source);await save()}));
      tools.append(button(course.paused?"恢复后续生成":"暂停后续生成",async()=>{course.paused=!course.paused;await save()}));
      tools.append(button("刷新",loadCourse));
      tools.append(button("删除课程（保留资料）",async()=>{if(!confirm("删除课程分组？视频、文档和笔记都会保留。"))return;await fetchJson(apiUrl(`/api/courses/${course.id}`),{method:"DELETE"});await loadOptions()}));
      const list=document.createElement("ol");list.className="course-sources";
      course.sources.forEach((source,index)=>{
        const row=document.createElement("li"), label=document.createElement("span");label.textContent=source.title||source.url;row.append(label);
        if(source.kind!=='url')row.append(button("打开",()=>{dialog.close();navigate(source)}));
        if(index>0)row.append(button("上移",async()=>{[course.sources[index-1],course.sources[index]]=[course.sources[index],course.sources[index-1]];await save()}));
        row.append(button("移出课程",async()=>{course.sources.splice(index,1);await save()}));list.append(row);
      });
      const urls=document.createElement("textarea");urls.placeholder="每行一个视频链接或 BV 号；B站分P可以分别添加带 p= 的链接。";urls.setAttribute("aria-label","批量视频链接");
      const addUrls=button("加入视频链接",async()=>{const values=urls.value.split(/\n+/).map(value=>value.trim()).filter(Boolean);course.sources.push(...values.map(url=>({kind:"url",url})));await save()});
      const previewList=document.createElement('ul');previewList.className='course-preview-list';
      const preview=button("展开播放列表 / 分P（最多24项）",async()=>{
        const result=await fetchJson(apiUrl('/api/courses/playlist-preview'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:urls.value.trim()})});
        previewList.replaceChildren();for(const source of result.sources){const item=document.createElement('li');item.textContent=`${source.title} — ${source.url}`;previewList.append(item)}
        urls.value=result.sources.map(item=>item.url).join('\n');status.textContent=`已展开 ${result.sources.length} 项，请检查后点击“加入视频链接”，尚未创建任务。`;
      });
      const generate=button("批量生成字幕笔记",async()=>{
        if(busy)return;
        const id=course.id;busy=true;generate.disabled=true;
        try{
          for(let count=0;count<24&&dialog.isConnected;count++){
            course=(await fetchJson(apiUrl(`/api/courses/${id}`))).course;
            if(course.paused){status.textContent="已暂停后续生成，已提交的任务可在资料库中管理。";break}
            const index=course.sources.findIndex(item=>item.kind==='url');if(index<0)break;
            const source=course.sources[index];status.textContent=`正在提交：${source.title||source.url}`;
            const task=await createTask(id,source.url);
            course=(await fetchJson(apiUrl(`/api/courses/${id}`))).course;
            const target=course.sources.findIndex(item=>item.kind==='url'&&item.url===source.url);
            if(target>=0){course.sources[target]={kind:"task",id:task.id};await save()}
          }
          status.textContent="本批提交结束。未提交的链接保留，可稍后继续；已提交任务按队列执行。";
        }finally{busy=false;if(dialog.isConnected&&course)render()}
      });
      generate.disabled=busy||course.paused||!course.sources.some(item=>item.kind==='url');
      const hint=document.createElement("p");hint.className="course-hint";hint.textContent="每批最多24个任务，使用当前转写与文字模型设置；本次不启用远程视觉。暂停只停止后续提交。";
      const importPanel=document.createElement('details');importPanel.className='course-import-panel';const importSummary=document.createElement('summary');importSummary.textContent='添加视频链接 / 播放列表';importPanel.append(importSummary,urls,preview,previewList,addUrls);
      const query=document.createElement("input");query.placeholder="对照关键词，例如 学习率 梯度";query.setAttribute("aria-label","课程对照关键词");
      const comparison=document.createElement("div");comparison.className="course-comparison";
      const compare=button("在课程中查找出处",async()=>{
        const result=await fetchJson(apiUrl(`/api/courses/${course.id}/compare?q=${encodeURIComponent(query.value)}`));comparison.replaceChildren();
        const warning=document.createElement("p");warning.textContent=result.warning;comparison.append(warning);
        for(const edge of result.edges){const p=document.createElement("p");p.textContent=`共同提到 ${edge.terms.join(' / ')}：${result.nodes.find(n=>n.id===edge.from)?.title} ↔ ${result.nodes.find(n=>n.id===edge.to)?.title}`;comparison.append(p)}
        for(const match of result.matches){const article=document.createElement("article"),h=document.createElement("strong"),quote=document.createElement("blockquote");h.textContent=`${match.title} · ${match.locator}`;quote.textContent=match.excerpt;article.append(h,quote,button("核对原文",()=>onEvidence(match.evidence_id)));comparison.append(article)}
        if(!result.matches.length){const p=document.createElement('p');p.textContent='这些资料中没有匹配出处，请换用更具体的关键词。';comparison.append(p)}
      });
      body.append(title,tools,list,importPanel);
      if(course.sources.some(item=>item.kind==='url'))body.append(hint,generate);
      body.append(query,compare,comparison);
    }
    select.onchange=()=>{activeCourseId=select.value;loadCourse().catch(error=>status.textContent=error.message)};
    createGroup.append(createSummary,courseTitle,create);
    const toolbar=document.createElement("div");toolbar.className="course-tools";toolbar.append(select,createGroup);
    const header=document.createElement('header');header.className='course-dialog-header';header.append(heading,close);
    dialog.append(header,toolbar,body,status);document.body.append(dialog);dialog.showModal();
    await loadOptions();
  }
  globalThis.LearnNoteCourses={open};
})();
