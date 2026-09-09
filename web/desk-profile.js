import { api, escapeHtml as esc } from "/web/desk-api.js";

export function installProfile({ state, notice }) {
  const button = document.createElement("button");
  button.id = "profile";
  button.textContent = "我的";
  button.title = "个人主页与用量";
  document.querySelector(".sidebar footer").prepend(button);
  const dialog = document.createElement("dialog");
  dialog.className = "profile-dialog";
  dialog.id = "profileDialog";
  dialog.innerHTML = '<header><div><span class="profile-eyebrow">个人主页</span><h2 id="profileName">我的学习空间</h2></div><button type="button" aria-label="关闭个人主页">×</button></header><div id="profileBody"></div>';
  document.body.append(dialog);
  dialog.querySelector("header button").onclick = () => dialog.close();
  dialog.addEventListener("click", event => { if(event.target === dialog && (event.clientX < dialog.getBoundingClientRect().left || event.clientX > dialog.getBoundingClientRect().right || event.clientY < dialog.getBoundingClientRect().top || event.clientY > dialog.getBoundingClientRect().bottom)) dialog.close(); });
  let generation = 0;
  async function openProfile() {
    if (!dialog.open) dialog.showModal();
    const epoch = ++generation;
    const body = dialog.querySelector("#profileBody");
    let name = "";
    try { name = localStorage.getItem("learnnote.profile.name") || ""; } catch {}
    dialog.querySelector("#profileName").textContent = name ? `${name}的学习空间` : "我的学习空间";
    body.innerHTML = '<p role="status">正在读取本机记录…</p>';
    const [usageResult, studyResult] = await Promise.allSettled([api("/api/model/usage"), api("/api/study/summary")]);
    if (epoch !== generation || !dialog.open) return;
    const usage = usageResult.status === "fulfilled" ? usageResult.value : null;
    const study = studyResult.status === "fulfilled" ? studyResult.value : null;
    const n = value => Number(value || 0).toLocaleString();
    const total = usage?.totals;
    const max = Math.max(1,...(usage?.daily || []).map(d=>d.total_tokens));
    body.innerHTML = `<form id="profileNameForm"><label for="profileNickname">称呼</label><div class="profile-inline"><input id="profileNickname" maxlength="32" placeholder="可选，仅保存在当前浏览器" value="${esc(name)}"><button>保存</button></div></form><div class="profile-stats"><section><span>我的内容</span><strong>${n(state.items.length)}</strong></section><section><span>累计 Token</span><strong>${total ? n(total.total_tokens) : "—"}</strong></section><section><span>模型请求</span><strong>${total ? n(total.requests) : "—"}</strong></section></div><section class="profile-section"><div class="profile-section-title"><h3>模型用量</h3><button type="button" id="profileRefresh">刷新</button></div>${usage ? `<p class="muted">输入 ${n(total.input_tokens)} · 输出 ${n(total.output_tokens)} · ${n(total.requests-total.measured_requests)} 次未返回用量</p><div class="usage-bars" aria-label="最近 14 天每日 Token，按 UTC 日期">${usage.daily.map(d=>`<div class="usage-day"><span>${esc(d.day.slice(5))}</span><meter min="0" max="${max}" value="${d.total_tokens}" aria-label="${esc(d.day)} ${d.total_tokens} Token"></meter><span>${n(d.total_tokens)}</span></div>`).join("") || '<p class="muted">第一次生成笔记或询问助手后，这里会显示用量。</p>'}</div><details><summary>按模型查看</summary>${usage.models.map(m=>`<p class="profile-model"><span>${esc(m.model)}<small>${esc(m.host)}</small></span><strong>${n(m.total_tokens)} Token</strong></p>`).join("") || '<p>暂无模型请求</p>'}</details><details><summary>最近请求</summary>${usage.recent.slice(0,20).map(r=>`<p class="profile-model"><span>${esc(r.model)}<small>${esc(new Date(r.at).toLocaleString())} · ${r.status === "success" ? "完成" : "未完成"}</small></span><span>${r.total_tokens == null ? "未返回用量" : n(r.total_tokens)+" Token"}</span></p>`).join("")}</details>` : '<p role="status">用量暂时无法读取，请刷新重试。</p>'}<p class="profile-footnote">仅记录本机更新后的请求，不代表账户额度或余额。未返回用量不会记为零；不保存提问和回答正文。</p></section><section class="profile-section"><h3>复习与积累</h3><p>${study ? `已建立 ${n(Object.entries(study.counts || {}).filter(([k])=>k!=="deleted").reduce((a,[k,b])=>a+Number(b),0))} 张复习卡 · 今日已评分 ${n(study.reviewed_today)} 次 · 当前到期 ${n(study.due_count)} 张` : "复习记录暂时无法读取"}</p><p class="muted">先回忆，再看答案。按“忘记了 / 有些困难 / 记住了 / 很轻松”评分，系统根据每张卡的记忆情况安排下一次复习。</p><button id="profileReview" type="button">开始复习</button></section>`;
    body.querySelector("#profileRefresh").onclick = openProfile;
    body.querySelector("#profileReview").onclick = () => { dialog.close(); document.getElementById("review").click(); };
    body.querySelector("#profileNameForm").onsubmit = event => {
      event.preventDefault();
      const value = body.querySelector("#profileNickname").value.trim();
      try { localStorage.setItem("learnnote.profile.name",value); dialog.querySelector("#profileName").textContent = value ? `${value}的学习空间` : "我的学习空间"; notice("称呼已保存"); }
      catch { notice("当前浏览器无法保存称呼"); }
    };
  }
  button.onclick = openProfile;
  window.addEventListener("hashchange",()=>{ if(location.hash === "#profile") openProfile(); });
  if(location.hash === "#profile") openProfile();
}
