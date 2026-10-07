(() => {
  const drafts=new Map();
  async function attach({container, kind, id, apiUrl, fetchJson}) {
    container.querySelector('.personal-notes')?.remove();
    const panel=document.createElement('details'); panel.className='personal-notes';
    const summary=document.createElement('summary'); summary.textContent='个人批注 · 重生成后保留';
    const list=document.createElement('div');
    const input=document.createElement('textarea'); input.placeholder='写下你的理解、疑问或补充'; input.setAttribute('aria-label','个人批注');input.maxLength=8000;
    input.value=drafts.get(`${kind}:${id}`)||'';input.oninput=()=>drafts.set(`${kind}:${id}`,input.value);
    const quote=document.createElement('p'); quote.className='personal-quote';
    const capture=document.createElement('button');capture.type='button';capture.textContent='引用选中的正文';
    capture.onclick=()=>{const selection=getSelection();const selected=selection?.anchorNode&&container.contains(selection.anchorNode)?String(selection).trim().slice(0,1000):'';quote.textContent=selected;quoteReanchored=Boolean(selected);};
    const save=document.createElement('button');save.type='button';save.textContent='保存批注';
    const status=document.createElement('p');status.setAttribute('role','status');
    const endpoint=apiUrl(`/api/personal/${kind}/${encodeURIComponent(id)}`);
    let editing='',editingAnchor={},quoteReanchored=false;
    const load=async()=>{
      const data=await fetchJson(endpoint);if(!panel.isConnected)return;list.replaceChildren();
      for(const item of data.annotations||[]){
        const article=document.createElement('article'), text=document.createElement('p'), citation=document.createElement('blockquote');text.textContent=item.text;citation.textContent=item.quote;
        const stale=Boolean(item.anchor_status?.stale);
        if(stale||item.quote&&!container.querySelector('.markdown-note')?.textContent.includes(item.quote)){const note=document.createElement('small');note.textContent=stale?(item.anchor_status?.repairable?'原文版本已变化；选择当前正文并保存以修复出处。':'原文版本已变化；这条批注没有可恢复的引用片段。'):'引用文本未在当前正文找到，可编辑并重新选择出处。';article.append(note);}
        const edit=document.createElement('button');edit.type='button';edit.textContent=stale?'修复出处':'编辑';edit.onclick=()=>{editing=item.id;editingAnchor=item.anchor&&typeof item.anchor==='object'?item.anchor:{};quoteReanchored=false;input.value=item.text;quote.textContent=item.quote;input.focus();};
        const remove=document.createElement('button');remove.type='button';remove.textContent='删除';remove.onclick=async()=>{if(!confirm('删除这条个人批注？'))return;try{await fetchJson(`${endpoint}/${encodeURIComponent(item.id)}`,{method:'DELETE'});await load()}catch(e){status.textContent=e.message}};
        article.append(citation,text,edit,remove);list.append(article);
      }
    };
    save.onclick=async()=>{if(!input.value.trim())return;save.disabled=true;try{const selected=quote.textContent.trim().slice(0,1000);let quoteHash='';if(quoteReanchored&&selected&&globalThis.crypto?.subtle){const digest=await globalThis.crypto.subtle.digest('SHA-256',new TextEncoder().encode(selected));quoteHash=[...new Uint8Array(digest)].map(value=>value.toString(16).padStart(2,'0')).join('')}const anchor=quoteReanchored&&selected?{...editingAnchor,source_revision:container.dataset.sourceRevision||'',selected_text:selected,quote_hash:quoteHash||editingAnchor.quote_hash||''}:editingAnchor;await fetchJson(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:input.value,quote:selected,id:editing,anchor})});editing='';editingAnchor={};quoteReanchored=false;input.value='';drafts.delete(`${kind}:${id}`);quote.textContent='';status.textContent='批注已保存在本机。';await load()}catch(e){status.textContent=e.message}finally{save.disabled=false}};
    panel.append(summary,list,input,capture,quote,save,status);container.append(panel);
    const exports=document.createElement('nav');exports.className='material-actions';
    for(const format of ['docx','pdf']){const link=document.createElement('a');link.textContent=`导出 ${format.toUpperCase()}（含个人批注）`;link.href=apiUrl(kind==='task'?`/api/tasks/${encodeURIComponent(id)}/exports/${format}?include_annotations=true`:`/api/library/materials/${encodeURIComponent(id)}/exports/${format}?include_annotations=true`);link.setAttribute('download','');exports.append(link)}
    panel.append(exports);
    panel.addEventListener('toggle',()=>{if(panel.open)load().catch(e=>status.textContent=e.message)});
  }
  globalThis.LearnNotePersonal={attach};
})();
