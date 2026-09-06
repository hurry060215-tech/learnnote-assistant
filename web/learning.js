/* Reading and review presentation; API and app navigation are injected. */
(() => {
  function markdownChunks(text) {
    const chunks = []; let lines = [], fence = "", length = 0;
    for (const line of String(text || "").split("\n")) {
      const match = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
      if (match && !fence) { fence = match[1][0]; length = match[1].length; }
      else if (match && match[1][0] === fence && match[1].length >= length && !match[2].trim()) fence = "";
      if (!fence && !line.trim() && lines.length) { chunks.push(lines.join("\n")); lines = []; }
      else lines.push(line);
    }
    if (lines.length) chunks.push(lines.join("\n"));
    return chunks;
  }
  function renderMaterial({container, material, text, markdownToHtml, apiUrl, onStudy}) {
    container.replaceChildren();
    const article = document.createElement("article"); article.className = "material-reader markdown-note";
    const toolbar = document.createElement("nav"); toolbar.className = "material-actions"; toolbar.setAttribute("aria-label", "资料操作");
    for (const [label, suffix] of [["原文件", "source"], ["Markdown", "exports/markdown"], ["Word", "exports/docx"], ["PDF", "exports/pdf"]]) {
      const link = document.createElement("a"); link.textContent = label;
      link.href = apiUrl(`/api/library/materials/${encodeURIComponent(material.material_id)}/${suffix}`); link.setAttribute("download", "");
      toolbar.append(link);
    }
    const study = document.createElement("button"); study.type = "button"; study.textContent = "生成复习卡片"; study.onclick = onStudy;
    toolbar.append(study); container.append(toolbar, article);
    const chunks = markdownChunks(text); let offset = 0;
    const more = document.createElement("button"); more.type = "button"; more.className = "secondary action-button material-load-more";
    const renderNext = () => {
      const group = document.createElement("div"); group.className = "material-page";
      group.innerHTML = markdownToHtml(chunks.slice(offset, offset + 50).join("\n\n"));
      offset = Math.min(chunks.length, offset + 50); article.append(group);
      more.textContent = `继续阅读（已显示 ${offset}/${chunks.length} 段）`; more.hidden = offset >= chunks.length;
      if (offset === chunks.length) more.remove();
    };
    more.onclick = renderNext; container.append(more); renderNext();
    return article;
  }
  function collapseContext(container) {
    const heading = [...container.querySelectorAll('.markdown-note h2')].find(node => node.textContent.trim() === '学习上下文');
    if (!heading || heading.closest('.note-context')) return;
    const details = document.createElement('details'); details.className = 'note-context';
    const summary = document.createElement('summary'); summary.textContent = '生成信息与学习提示'; details.append(summary);
    heading.before(details);
    let node = heading;
    while (node) {
      const next = node.nextSibling;
      if (node !== heading && node.nodeType === 1 && /^H[12]$/.test(node.tagName)) break;
      details.append(node); node = next;
    }
    if (!container.dataset.contextLinksBound) {
      container.dataset.contextLinksBound = 'true';
      container.addEventListener('click', event => {
        const link = event.target.closest?.('a[href^="#"]');
        const target = link && document.getElementById(link.getAttribute('href').slice(1));
        const parent = target?.closest('details'); if (parent) parent.open = true;
      });
    }
  }
  function attachOcr({container,task,fetchJson,apiUrl,onSeek}) {
    if (!task.options?.local_ocr) return;
    const panel=document.createElement('details');panel.className='ocr-evidence';
    const summary=document.createElement('summary');summary.textContent='画面文字（本地OCR，待核对）';
    const content=document.createElement('div');panel.append(summary,content);container.append(panel);
    panel.addEventListener('toggle',async()=>{
      if(!panel.open)return;
      try{
        const result=await fetchJson(apiUrl(`/api/tasks/${encodeURIComponent(task.id)}/ocr`));
        content.replaceChildren();const warning=document.createElement('p');warning.textContent=result.warning||'文字识别仍在准备；有字幕时可以先阅读笔记。';content.append(warning);
        for(const frame of result.frames||[]){
          const section=document.createElement('section');
          const parsed=new URL(frame.image_url||'',location.href);
          if(parsed.pathname.startsWith(`/api/tasks/${task.id}/frames/`)){const image=document.createElement('img');image.src=apiUrl(parsed.pathname);image.alt=`${frame.timestamp}秒的原始关键帧`;image.loading='lazy';section.append(image)}
          const seek=document.createElement('button');seek.type='button';seek.textContent=`回看 ${Math.floor(frame.timestamp/60)}:${String(Math.floor(frame.timestamp%60)).padStart(2,'0')}`;seek.onclick=()=>onSeek(frame.timestamp);section.append(seek);
          for(const line of frame.lines||[]){const p=document.createElement('p');p.textContent=`${line.text} （识别置信度 ${(line.confidence*100).toFixed(1)}%，未核验）`;section.append(p)}
          content.append(section);
        }
        if(result.frames?.length){const download=document.createElement('a');download.textContent='导出识别结果 JSON';download.href=apiUrl(`/api/tasks/${encodeURIComponent(task.id)}/ocr`);download.download=`ocr-${task.id}.json`;content.append(download)}
      }catch(error){content.textContent=error.message||'无法读取本地识别结果。'}
    });
  }
  async function openEvidence({id, fetchJson, apiUrl, navigate}) {
    const before = document.activeElement;
    const dialog = document.createElement("dialog"); dialog.className = "source-dialog";
    const title = document.createElement("h2"); title.textContent = "原文出处";
    const body = document.createElement("pre"); body.textContent = "正在读取本地原文…";
    const close = document.createElement("button"); close.textContent = "关闭"; close.type = "button";
    close.onclick = () => dialog.close(); dialog.addEventListener("close", () => { dialog.remove(); before?.focus?.(); });
    dialog.append(title, close, body); document.body.append(dialog); dialog.showModal();
    try {
      const {evidence} = await fetchJson(apiUrl(`/api/knowledge/evidence/${encodeURIComponent(id)}`));
      if (!dialog.isConnected) return;
      title.textContent = `${evidence.title || "原文"} · ${evidence.locator || "出处"}`; body.textContent = evidence.text;
      if (evidence.task_id || evidence.metadata?.material_id) {
        const link = document.createElement("button"); link.type = "button"; link.textContent = "打开来源资料";
        link.onclick = () => { dialog.close(); navigate(evidence); }; dialog.append(link);
      }
    } catch (error) { body.textContent = error?.message || "原文不可用，请重新关联。"; }
  }
  function renderStudy({els, cards, summary, plan, onReview, onSource, onCreate, onPlan}) {
    const reviewed = Number(summary.reviewed_today || 0), target = Math.max(1, Number(plan.daily_target || 10));
    const paused = Boolean(plan.paused), due = Number(summary.due_count || 0);
    els.studyViewSummary.innerHTML = `<span><b>${due}</b><small>${summary.course_scope?'本次课程卡片':'张到期卡片'}</small></span><span><b>${reviewed}</b><small>今日已复习（全部资料）</small></span><span><b>${target}</b><small>每日目标</small></span>`;
    const percent = Math.max(0, Math.min(100, Math.round(100 * reviewed / target)));
    els.studyViewProgressLabel.textContent = `${reviewed} / ${target}`;
    els.studyViewProgressBar.style.width = `${percent}%`; els.studyViewProgressBar.parentElement?.setAttribute("aria-valuenow", String(percent));
    els.studyViewProgressHint.textContent = paused ? "学习计划已暂停" : !cards.length ? "今天没有待复习卡片" : reviewed >= target ? "今日目标已完成" : `本次可复习 ${Math.min(due, target - reviewed)} 张 · ${plan.timezone || "UTC"}`;
    const container = els.studyViewDueList; container.replaceChildren();
    if (paused || !cards.length) {
      const p = document.createElement("p"); p.textContent = paused ? "记录已保留，恢复计划后继续。" : "到期资料已复习完。也可以从已有资料生成新的卡片。";
      const button = document.createElement("button"); button.type = "button"; button.className = "primary action-button";
      button.textContent = paused ? "管理学习计划" : "选择学习资料"; button.onclick = paused ? onPlan : onCreate;
      container.append(p, button); return;
    }
    let index = 0;
    const show = () => {
      container.replaceChildren(); const card = cards[index];
      if (!card) { const p = document.createElement("p"); p.textContent = "本次复习已完成。"; container.append(p); return; }
      const article = document.createElement("article"); article.className = "study-card";
      const count = document.createElement("small"); count.textContent = `第 ${index + 1} / ${cards.length} 张`;
      const front = document.createElement("h3"); front.textContent = card.front;
      const answer = document.createElement("p"); answer.textContent = card.back; answer.hidden = true; answer.className = "study-answer";
      const reveal = document.createElement("button"); reveal.type = "button"; reveal.textContent = "显示答案"; reveal.className = "primary action-button";
      const controls = document.createElement("div"); controls.className = "study-card-actions"; controls.hidden = true;
      reveal.onclick = () => { answer.hidden = false; controls.hidden = false; reveal.hidden = true; answer.tabIndex = -1; answer.focus(); };
      for (const [rating, label] of [[1,"重来"],[2,"困难"],[3,"记住"],[4,"简单"]]) {
        const button = document.createElement("button"); button.type = "button"; button.textContent = label;
        // Retrying after an uncertain response reuses this logical submission.
        const idempotencyKey = globalThis.crypto.randomUUID();
        button.onclick = async () => {
          controls.querySelectorAll("button").forEach(b => b.disabled = true);
          try {
            const fresh = await onReview(card.card_id, rating, idempotencyKey);
            if (fresh?.view_changed) return;
            const completed = Number(fresh?.reviewed_today || reviewed + index + 1);
            els.studyViewProgressLabel.textContent = `${completed} / ${target}`;
            const percentage = Math.min(100, Math.round(completed * 100 / target));
            els.studyViewProgressBar.style.width = `${percentage}%`;
            els.studyViewProgressBar.parentElement?.setAttribute("aria-valuenow", String(percentage));
            const values = els.studyViewSummary.querySelectorAll("b");
            if (values[0]) values[0].textContent = String(fresh?.due_count ?? Math.max(0, due - index - 1));
            if (values[1]) values[1].textContent = String(completed);
            els.studyViewProgressHint.textContent = completed >= target ? "今日目标已完成" : "复习记录已保存";
            index++; show();
          }
          catch (error) { status.textContent = error.message || "提交失败，可重试。"; controls.querySelectorAll("button").forEach(b => b.disabled = false); }
        }; controls.append(button);
      }
      const sources = document.createElement("div"); sources.className = "study-card-sources";
      for (const id of card.source_evidence_ids || []) { const b = document.createElement("button"); b.type = "button"; b.textContent = "查看原文出处"; b.onclick = () => onSource(id); sources.append(b); }
      const status = document.createElement("p"); status.setAttribute("role", "status");
      article.append(count, front, reveal, answer, controls, sources, status); container.append(article);
    }; show();
  }
  function renderStudyHistory({dashboard,onSource}) {
    const root=document.querySelector('#studyView');if(!root)return;root.querySelector('.study-review-history')?.remove();
    const details=document.createElement('details');details.className='study-review-history';const summary=document.createElement('summary');summary.textContent='近期复习与需要重温的卡片';
    const label=document.createElement('p');label.textContent='最近14天的全部本地复习记录；评分来自你的自评，不代表课程平台进度或考试成绩。';
    const activity=document.createElement('div');activity.className='study-activity';
    for(const day of dashboard.progress?.activity||[]){const cell=document.createElement('span');cell.textContent=String(day.review_count);cell.title=`${day.date}：复习 ${day.review_count} 张`;cell.setAttribute('aria-label',cell.title);cell.style.opacity=day.review_count?'.95':'.45';activity.append(cell)}
    const heading=document.createElement('h3');heading.textContent=dashboard.course_id?'此课程中曾选择“重来”的卡片':'曾选择“重来”的卡片';
    details.append(summary,label,activity,heading);
    for(const item of dashboard.mistakes||[]){const article=document.createElement('article'),question=document.createElement('strong'),answer=document.createElement('p');question.textContent=item.question;answer.textContent=item.answer;article.append(question,answer);for(const id of item.source_evidence_ids||[]){const button=document.createElement('button');button.type='button';button.textContent='回原文重温';button.onclick=()=>onSource(id);article.append(button)}details.append(article)}
    if(!dashboard.mistakes?.length){const empty=document.createElement('p');empty.textContent='当前范围没有“重来”记录。';details.append(empty)}root.append(details);
  }
  globalThis.LearnNoteLearning = {markdownChunks, renderMaterial, renderStudy, renderStudyHistory, openEvidence, collapseContext, attachOcr};
})();
