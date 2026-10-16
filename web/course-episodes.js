import { api, escapeHtml as esc } from "/web/desk-api.js";
import { episodeScope as snapshot, episodeEndpoint as endpoint } from "/web/course-episode-retry.js";

const routeKey = route => route ? JSON.stringify([route.base_url, route.model]) : "";
const copy = value => JSON.parse(JSON.stringify(value));
const upgradeOptions = value => {
  const result = { ...copy(value), content_mode: "visual", visual_understanding: true, use_saved_connection: true };
  for (const key of ["llm_api_key", "llm_base_url", "llm_model"]) delete result[key];
  return result;
};
export function episodeActionsHtml(episode, paused = false) {
  if (!episode) return "";
  const disabled = paused ? "disabled" : "", id = esc(episode.episode_id);
  const retry = episode.retryable ? `<button data-retry-episode="${id}" ${disabled}>${episode.retry_kind === "summary" ? "重试字幕总结" : "恢复此集"}</button>` : "";
  const upgrade = episode.caption_upgrade_available ? `<button data-upgrade-episode="${id}" ${disabled}>补充画面笔记…</button>` : "";
  const labels = { queued: "排队中", running: "处理中", success: "已完成", failed: "失败", cancelled: "已取消", interrupted: "中断" };
  const children = (episode.upgrades || []).map(item => `<button data-open-upgrade="${esc(item.task_id)}">画面笔记 · ${esc(labels[item.status] || "查看")}</button>`).join("");
  return retry || upgrade || children ? `<div class="tool-actions section-review">${retry}${upgrade}${children}</div>` : "";
}

// A review is bound to its original episode, dialog generation and saved model.
export function installCourseEpisodes({ state, dialog, show, status, generation, options, guard, refresh, openCourse, openItem, setCourseBack = () => {} }) {
  const pending = new Set();
  let active = null, navigation = 0;
  const currentView = (token, epoch, visit) => dialog.open && token === generation() && epoch === state.epoch && visit === navigation;
  function discard(scope, preview) {
    if (preview?.preview_id) void api(`${endpoint(scope)}/upgrade-preview/${encodeURIComponent(preview.preview_id)}`, { method: "DELETE" }).catch(() => {});
  }
  function invalidate() {
    const old = active; active = null;
    if (old && !old.submitted) discard(old.scope, old.preview);
    old?.clear?.();
  }
  for (const name of ["cancel", "learnnote:dialog-closed"]) dialog.addEventListener(name, invalidate);
  dialog.addEventListener("close", () => { if (!dialog.open) invalidate(); });
  window.addEventListener("learnnote:navigation", () => { const owned = active?.owns(); invalidate(); navigation++; if (owned) dialog.close(); });
  window.addEventListener("learnnote:settings", () => {
    const owned = active?.owns(); invalidate();
    if (owned) status("模型或处理设置已变化，本次确认已失效。请返回课程重新预览。");
  });
  async function openLinked(taskId) {
    if (!guard()) return;
    const token = generation(), epoch = state.epoch, visit = navigation;
    const result = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
    if (!currentView(token, epoch, visit)) return;
    if (result.task?.id !== taskId) throw new Error("关联画面任务不可用，请刷新分集状态。");
    dialog.close(); await openItem({ ...result.task, kind: "task" });
  }
  async function review(course, episode) {
    if (!guard()) return;
    const scope = snapshot(course, episode), selected = upgradeOptions(options()), key = endpoint(scope), title = String(episode.title || "此分集");
    if (!episode.caption_upgrade_available) return;
    if (pending.has(key)) { status("此分集的上次请求仍在处理中，请稍后刷新课程核对。"); return; }
    const epoch = state.epoch, visit = navigation;
    const token = show("补充画面笔记", '<p class="muted">正在读取已保存的模型与媒体预算…</p>');
    setCourseBack(scope.course_id);
    const session = { scope, preview: null, submitted: false, owns: () => active === session && dialog.open && token === generation(), current: () => active === session && currentView(token, epoch, visit) };
    active = session;
    const $ = id => document.getElementById(id);
    const body = $("toolBody");
    const unchanged = () => JSON.stringify(upgradeOptions(options())) === JSON.stringify(selected);
    pending.add(key);
    try {
      const saved = await api("/api/model/connection");
      if (!session.current()) return;
      if (!saved.configured || !saved.model?.base_url || !saved.model?.model) throw new Error("请先在设置中保存有效的视觉模型连接，再重新预览。");
      if (!unchanged()) throw new Error("处理设置已变化，请重新预览。");
      const route = { base_url: saved.model.base_url, model: saved.model.model };
      const preview = await api(`${key}/upgrade-preview`, { method: "POST", body: JSON.stringify({ revision: scope.revision, options: selected, ...route }) });
      if (!session.current()) { discard(scope, preview); return; }
      session.preview = preview;
      if (preview.source_task_id !== scope.task_id || preview.episode_id !== scope.episode_id || routeKey(preview.connection) !== routeKey(route)
          || typeof preview.model_source?.title !== "string" || typeof preview.model_source?.url !== "string"
          || !preview.preview_id || !preview.fingerprint || !Number.isFinite(preview.resource_budget_mb) || preview.resource_budget_mb <= 0
          || ["max_frame_count", "frame_interval", "vision_batch_size"].some(key => !Number.isInteger(preview.options?.[key]) || preview.options[key] < 1))
        throw new Error("预览的来源、模型或预算已变化，请刷新分集状态后重新预览。");
      body.innerHTML = `<section class="course-upgrade section-review"><p><strong>${esc(preview.title || title)}</strong></p>
        <p>下载来源网址：<span class="answer">${esc(preview.page_url)}</span></p>
        <p>每集媒体/处理预算：${esc(preview.resource_budget_mb)} MB。字幕任务没有可复用的视频，需要重新获取完整来源。此预算在下载后检查媒体大小；下载流量可能超过此数值才被拒绝。</p>
        <p>画面设置：基础抽帧间隔 ${esc(preview.options.frame_interval)} 秒；设置抽帧上限 ${esc(preview.options.max_frame_count)} 帧；每批最多 ${esc(preview.options.vision_batch_size)} 张画面网格。低资源模式或模型限制可能进一步降低数量；可能分多批调用模型，费用总额未知。</p>
        <p>模型发送目标：<span class="answer">${esc(preview.connection.model)} · ${esc(preview.connection.base_url)}</span></p>
        <p>发送给模型的来源标题：<span class="answer">${esc(preview.model_source.title || "（空）")}</span></p>
        <p>发送给模型的来源网址：<span class="answer">${esc(preview.model_source.url || "（空）")}</span></p>
        <p class="muted">识别到的凭据信息已遮盖，仍请核对。已有字幕文本、上方模型来源标题与网址、从视频提取的画面会发送到上述模型地址，可能产生费用，金额未知；本机网关也可能转发。</p>
        <p class="muted">${esc(preview.warning || "请确认来源访问与使用权限。")}</p>
        <p>原字幕笔记与课程分集保持不变。完成后会新增一份关联的画面笔记。</p>
        <label class="tool-choice"><input type="checkbox" id="courseUpgradeDownload"><span>我确认可访问和使用此来源，同意重新下载视频，也了解上述预算不是下载流量上限。</span></label>
        <label class="tool-choice"><input type="checkbox" id="courseUpgradeShare"><span>我同意将已有字幕文本、上方模型来源标题与网址和提取画面发送到上述模型地址进行分析（可能收费）。</span></label>
        <footer><button type="button" id="courseUpgradeCancel">取消</button><button type="button" class="primary" id="courseUpgradeConfirm" disabled>确认下载并补充画面笔记</button></footer>
        <p class="muted">提交前取消会使本次确认失效；提交后关闭窗口不会停止已排队的下载或模型请求，请在资料库管理任务。</p></section>`;
      const download = $("courseUpgradeDownload"), share = $("courseUpgradeShare"), submit = $("courseUpgradeConfirm"), cancel = $("courseUpgradeCancel");
      session.clear = () => { download.checked = share.checked = false; download.disabled = share.disabled = submit.disabled = true; };
      const sync = () => { submit.disabled = !session.current() || session.submitted || !download.checked || !share.checked || pending.has(key); };
      download.addEventListener("change", sync); share.addEventListener("change", sync);
      cancel.addEventListener("click", async event => { event.stopPropagation(); if (!session.current()) return; invalidate(); await openCourse(scope.course_id); });
      submit.addEventListener("click", async event => {
        event.stopPropagation();
        if (!session.current() || session.submitted || pending.has(key) || !download.checked || !share.checked || !guard()) return;
        pending.add(key); session.clear(); status("正在核对所选模型并提交关联任务…");
        try {
          const connection = await api("/api/model/connection");
          if (!session.current()) return;
          if (!unchanged() || !connection.configured || routeKey(connection.model) !== routeKey(preview.connection)) throw new Error("模型或处理设置已变化，请重新预览。");
          session.submitted = true;
          const result = await api(`${key}/upgrade`, { method: "POST", body: JSON.stringify({ preview_id: preview.preview_id, fingerprint: preview.fingerprint, confirm_download: true, share_images: true }) });
          if (!session.current()) return;
          if (result.source_task_id !== scope.task_id || result.episode_id !== scope.episode_id || !result.task_id || result.task?.id !== result.task_id)
            throw new Error("返回的关联任务身份不一致，请刷新课程核对。");
          body.innerHTML = `<p>关联画面任务已${result.deduplicated ? "复用" : "创建"}。原字幕笔记与课程分集仍保留。</p><div class="tool-actions"><button type="button" id="courseUpgradeOpen">打开关联画面任务</button><button type="button" id="courseUpgradeReturn">返回课程</button></div>`;
          $("courseUpgradeOpen").addEventListener("click", async event => { event.stopPropagation(); if (!session.current()) return; try { await openLinked(result.task_id); } catch (error) { if (session.current()) status(error.message); } });
          $("courseUpgradeReturn").addEventListener("click", async event => { event.stopPropagation(); if (session.current()) await openCourse(scope.course_id); });
          status("任务进度可在资料库或此课程的关联画面笔记中查看。");
          // Refresh only the current accepted view; late responses never reopen it.
          await refresh().catch(() => { if (session.current()) status("关联任务已创建；资料库暂未刷新，请稍后刷新查看。"); });
        } catch (error) {
          if (session.current()) { invalidate(); status(`${error.message} 不会自动重试；请返回课程核对已有任务，再重新预览。`); }
        } finally { pending.delete(key); }
      });
      session.sync = sync;
      status("请分别核对下载与画面分享，两个选项均确认后才会提交。");
    } catch (error) {
      if (session.current()) { invalidate(); body.innerHTML = '<p>未提交画面任务。请返回课程后重新预览。</p>'; status(error.message); }
    } finally { pending.delete(key); if (session.current()) session.sync?.(); }
  }
  return { review, openLinked, invalidate };
}
