import { api } from "/web/desk-api.js";

export const episodeEndpoint = scope => `/api/courses/${encodeURIComponent(scope.course_id)}/episodes/${encodeURIComponent(scope.episode_id)}`;

export function episodeScope(course, episode) {
    if (!course?.id || !Number.isInteger(course.revision) || !episode?.episode_id || !episode.task_id || course.paused)
      throw new Error("课程已暂停或分集不可用，请刷新分集状态。");
    return { course_id: course.id, revision: course.revision, episode_id: episode.episode_id, task_id: episode.task_id, generation: episode.generation };
  }

export function installCourseRetry({ state, dialog, generation, options, guard, refresh, openCourse, status }) {
  const pending = new Set();
  let navigation = 0;
  window.addEventListener("learnnote:navigation", () => navigation++);
  const currentView = (token, epoch, visit) => dialog.open && token === generation() && epoch === state.epoch && visit === navigation;
  async function retry(course, episode) {
    if (!guard()) return;
    const scope = episodeScope(course, episode), token = generation(), epoch = state.epoch, visit = navigation;
    const current = () => currentView(token, epoch, visit), key = episodeEndpoint(scope);
    if (!episode.retryable || pending.has(key)) return;
    const summary = episode.retry_kind === "summary";
    const selected = JSON.parse(JSON.stringify(options()));
    if (summary) Object.assign(selected, { content_mode: "text", visual_understanding: false, local_ocr: false });
    if (!confirm(summary ? "使用已有字幕重试文字总结？使用当前文字模型设置，不重新下载视频，也不分析画面。" : "从此分集已有媒体和检查点恢复？使用当前模型设置，不创建重复分集。") || !current()) return;
    pending.add(key);
    try {
      await api(`${key}/retry`, { method: "POST", body: JSON.stringify({ revision: scope.revision, task_id: scope.task_id, generation: scope.generation, options: selected }) });
      if (!current()) return;
      await refresh();
      if (current()) await openCourse(scope.course_id);
    } catch (error) { if (current()) status(`${error.message} 不会自动重试，请刷新分集状态后再决定。`); }
    finally { pending.delete(key); }
  }
  return retry;
}
