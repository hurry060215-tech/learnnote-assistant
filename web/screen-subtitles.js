import { escapeHtml as esc, timestamp } from "/web/desk-api.js";

export function screenSubtitleSettings(form) {
  const value = (name) => Number(form.elements.namedItem(name).value);
  const settings = {
    crop_left: value("cropLeft") / 100, crop_top: value("cropTop") / 100,
    crop_right: value("cropRight") / 100, crop_bottom: value("cropBottom") / 100,
    interval_seconds: value("interval"), language: form.elements.namedItem("language").value,
  };
  if (![settings.crop_left, settings.crop_top, settings.crop_right, settings.crop_bottom, settings.interval_seconds].every(Number.isFinite)
      || settings.crop_left < 0 || settings.crop_top < 0 || settings.crop_right > 1 || settings.crop_bottom > 1
      || settings.crop_left >= settings.crop_right || settings.crop_top >= settings.crop_bottom
      || settings.interval_seconds < .25 || settings.interval_seconds > 10)
    throw new Error("请填写有效的裁剪范围和抽样间隔。");
  return settings;
}

export function screenSubtitleResultHtml(report) {
  if (!report || report.status === "not_started") return "<p>此任务还没有画面字幕结果。</p>";
  const labels = { running: "正在提取", ready: "抽样处理完成，识别结果待核对", empty: "没有识别出所选文字", partial: "仅有部分覆盖", failed: "提取失败", cancelled: "已取消，完成窗口已保留" };
  const coverage = report.coverage || {};
  return `<p><strong>${esc(labels[report.status] || report.status)}</strong></p><p>${esc(report.warning || "")}</p>
    <p>已处理 ${Number(coverage.sampled_seconds || 0).toFixed(1)} / ${Number(coverage.requested_seconds || 0).toFixed(1)} 秒的抽样窗口；复用 ${Number(report.cache_hits || 0)} 个窗口。</p>
    <p class="muted">抽样覆盖不代表识别了全部字幕。字幕时间是估计值；不确定文字请回看原画面。</p>
    ${report.invalid_cache_windows?.length ? `<p>有 ${report.invalid_cache_windows.length} 个缓存窗口未通过校验，已重新处理。</p>` : ""}
    ${report.failed_windows?.length ? `<p>有 ${report.failed_windows.length} 个窗口未完成，不能作为完整字幕笔记。</p>` : ""}
    ${(report.cues || []).slice(0, 100).map(cue => `<details><summary>${esc(timestamp(cue.start))}–${esc(timestamp(cue.end))} · ${esc(cue.text)}</summary><p>最低识别置信度 ${Math.round(Number(cue.confidence || 0) * 100)}% · 未人工核验 · ${Number(cue.sample_count || 0)} 次抽样</p>${(cue.lines || []).map(line => `<p>${esc(line.text)} · ${Math.round(Number(line.confidence || 0) * 100)}%<small> 画面坐标 ${esc(JSON.stringify(line.bbox))}</small></p>`).join("")}</details>`).join("")}
    ${(report.cues || []).length > 100 ? `<p>预览前 100 / ${report.cues.length} 段；完整结果保存在字幕与 JSON 导出中。</p>` : ""}`;
}

export async function mountScreenSubtitles(root, { source, api, options, isCurrent, openTask, refresh, status }) {
  const id = encodeURIComponent(source.id);
  let sequence = 0, busy = false, restoredSettings = false;
  const active = () => root.isConnected && isCurrent();
  const cropInput = (name, label, value) => `<label>${label}（%）<input name="${name}" type="number" min="0" max="100" step="1" value="${value}" required></label>`;
  root.innerHTML = `<p>使用这份任务已保存的视频，创建独立画面字幕结果。原音频转写、笔记和个人修订都会保留，不重新下载或转写音频。</p>
    ${source.learning_range?.original_start != null ? `<p>当前任务是视频片段：片段时间 0 秒对应原视频 ${esc(source.learning_range.original_start)} 秒。本次处理此任务已保存的整个片段。</p>` : ""}
    <p class="muted">起始裁剪是底部 26%，间隔 0.5 秒，仅供试选。请先预览并按此视频调整；字幕位置、速度和画面清晰度都会影响结果。</p>
    <form data-screen-form><fieldset><legend>字幕裁剪范围</legend>
    ${cropInput("cropLeft", "左边界", 0)}${cropInput("cropRight", "右边界", 100)}${cropInput("cropTop", "上边界", 74)}${cropInput("cropBottom", "下边界", 100)}</fieldset>
    <label>抽样间隔（秒）<input name="interval" type="number" min="0.25" max="10" step="0.25" value="0.5" required></label>
    <label>保留文字<select name="language"><option value="auto">全部文字（包括中英双语）</option><option value="zh">含中文字行</option><option value="en">含英文字母行</option></select></label>
    <p class="muted">语言选项只筛选文字行，不会翻译，也不会修正专业词。双语在同一行时会保留整行。</p>
    <label>预览位置（秒）<input name="previewTime" type="number" min="0" step="0.5" value="0"></label>
    <button type="button" data-preview-screen>预览裁剪与识别文字</button><div data-screen-preview aria-live="polite"></div>
    <label class="check"><input name="generateNote" type="checkbox">提取完成后，使用当前选定的文字模型生成新笔记（会将识别文本发送给该模型，并可能产生用量费用）</label>
    <footer><button class="primary" type="submit" data-start-screen>提取画面字幕</button></footer></form>
    <hr><div class="tool-actions"><button type="button" data-refresh-screen>刷新提取结果</button><button type="button" data-resume-screen hidden>从已验证窗口恢复</button><button type="button" data-cancel-screen hidden>取消提取</button></div>
    <div data-screen-result aria-live="polite"></div><a class="tool-link" href="/api/tasks/${id}/screen-subtitles" download>导出完整画面字幕与置信度 JSON ↗</a>`;
  const form = root.querySelector("form");
  const controls = () => [...root.querySelectorAll("button")];
  async function run(work) {
    if (busy || !active()) return;
    busy = true; controls().forEach(button => button.disabled = true);
    try { await work(); } catch (error) { if (active()) status(error.message); }
    finally { busy = false; if (active()) controls().forEach(button => button.disabled = false); }
  }
  form.addEventListener("input", () => {
    sequence++;
    root.querySelector("[data-screen-preview]").replaceChildren();
    root.querySelector("[data-start-screen]").textContent = form.elements.namedItem("generateNote").checked ? "提取画面字幕并生成笔记" : "提取画面字幕";
  });
  root.querySelector("[data-preview-screen]").onclick = () => run(async () => {
    if (!form.reportValidity()) return;
    const token = ++sequence;
    const result = await api(`/api/tasks/${id}/screen-subtitles/preview`, { method: "POST", body: JSON.stringify({ settings: screenSubtitleSettings(form), timestamp: Number(form.elements.namedItem("previewTime").value) }) });
    if (!active() || token !== sequence) return;
    const view = root.querySelector("[data-screen-preview]");
    view.innerHTML = `<p>${esc(result.warning)}</p><p>实际画面时间 ${esc(timestamp(result.frame_timestamp))}</p>${(result.lines || []).map(line => `<p>${esc(line.text)} · ${Math.round(Number(line.confidence || 0) * 100)}% · ${line.selected ? "保留，未核验" : "被语言筛选排除"}</p>`).join("") || "<p>未识别到文字，请调整裁剪或预览位置。</p>"}`;
    if (/^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(result.image_url || "")) {
      const image = document.createElement("img"); image.src = result.image_url; image.alt = "所选字幕裁剪范围";
      image.style.maxWidth = "100%"; view.prepend(image);
    }
  });
  form.onsubmit = event => {
    event.preventDefault();
    event.stopPropagation();
    run(async () => {
      if (!form.reportValidity()) return;
      const generate = form.elements.namedItem("generateNote").checked;
      const result = await api(`/api/tasks/${id}/screen-subtitles`, { method: "POST", body: JSON.stringify({ settings: screenSubtitleSettings(form), generate_note: generate, options: generate ? options() : null }) });
      await refresh();
      if (active()) await openTask(result);
    });
  };
  async function results() {
    const token = ++sequence;
    const [report, detail] = await Promise.all([api(`/api/tasks/${id}/screen-subtitles`), api(`/api/tasks/${id}`)]);
    if (!active() || token !== sequence) return;
    root.querySelector("[data-screen-result]").innerHTML = screenSubtitleResultHtml(report);
    const task = detail.task;
    const running = ["queued", "running", "cancelling"].includes(task.status);
    root.querySelector("[data-resume-screen]").hidden = task.mode !== "screen_subtitles" || !["failed", "cancelled"].includes(task.status);
    root.querySelector("[data-cancel-screen]").hidden = task.mode !== "screen_subtitles" || !running;
    if (!restoredSettings && task.options?.screen_subtitles && task.mode === "screen_subtitles") {
      restoredSettings = true;
      const saved = task.options.screen_subtitles;
      for (const [field, key] of [["cropLeft", "crop_left"], ["cropTop", "crop_top"], ["cropRight", "crop_right"], ["cropBottom", "crop_bottom"]]) form.elements.namedItem(field).value = saved[key] * 100;
      form.elements.namedItem("interval").value = saved.interval_seconds;
      form.elements.namedItem("language").value = saved.language;
    }
  }
  root.querySelector("[data-refresh-screen]").onclick = () => run(results);
  root.querySelector("[data-resume-screen]").onclick = () => run(async () => {
    await api(`/api/tasks/${id}/screen-subtitles/resume`, { method: "POST" });
    if (active()) status("正在用原设置校验并恢复；修改设置需要创建新的提取任务。");
    await refresh(); await results();
  });
  root.querySelector("[data-cancel-screen]").onclick = () => run(async () => {
    await api(`/api/tasks/${id}/cancel`, { method: "POST" });
    if (active()) status("已请求取消；已验证的完整窗口将保留。");
    await refresh(); await results();
  });
  await run(results);
}
