// Fresh per-task choices. Rendering and cancellation never submit a task.
export function reviewTaskModelData({ task, options, health = {}, isCurrent = () => true, doc = document, events = window }) {
  const preview = task.model_data_preview;
  if (!preview?.fingerprint) return Promise.reject(new Error("发送范围暂时不可用，请刷新任务后再确认。"));
  if (options.content_mode === "subtitles" || preview.mode === "download_only") {
    return Promise.resolve({ allow_model_page_context: false, allow_page_text_fallback: false, review_fingerprint: preview.fingerprint });
  }
  let host = "当前配置的服务";
  try { host = new URL(options.llm_base_url || health.default_llm_base_url).host; } catch {}
  const model = options.llm_model || health.default_llm_model || "当前配置的模型";
  const dialog = doc.createElement("dialog");
  dialog.className = "tools-dialog";
  let content = dialog;
  dialog.setAttribute("aria-labelledby", "modelDataConsentTitle");
  const add = (tag, text, parent = content) => {
    const element = doc.createElement(tag); element.textContent = text; parent.append(element); return element;
  };
  const header = add("header", "");
  const heading = add("h2", "确认这次任务发送的资料", header);
  heading.id = "modelDataConsentTitle"; heading.tabIndex = -1;
  content = add("section", ""); content.className = "section-review";
  add("p", `接收方：${host} · ${model}。本机网关也可能转发；模型服务可能收费。`);
  add("p", "来源标题：" + (preview.title || "未命名"));
  add("p", "来源页面链接：" + (preview.source_url || "无"));
  add("p", "获取来源时可能以发现的标题替换当前标题；发现的标题也按相同规则遮盖常见凭据后发送。");
  const textTask = preview.mode === "page_text";
  add("p", textTask
    ? `本次明确使用页面文本：发送清理后的页面文字（最多 ${preview.page_text_limit.toLocaleString()} 字符）、浏览器字幕线索（最多 ${preview.subtitle_text_limit.toLocaleString()} 字符）及整理要求。`
    : `发送必要字幕${options.visual_understanding ? "、选定画面" : ""}及整理要求。页面上下文和页面全文兜底分别选择；两项均默认不发送。`);
  if (!textTask && ["openai", "openai-compatible", "openai-compatible-asr", "groq", "groq-asr"].includes(options.transcriber)) {
    add("p", `如果没有可验证字幕，音频会发送到 ${host} 的音频转写接口（与文字模型共用地址）。`);
  }
  add("p", "标题、链接和页面文本已按现有规则遮盖常见凭据；遮盖不是完整的隐私检查，请审阅下方文字。取消不会开始任务或调用模型。原始采集资料仍保留在本机。");
  const check = (id, text) => {
    const label = add("label", ""); label.className = "tool-choice";
    const input = doc.createElement("input"); input.type = "checkbox"; input.id = id; input.checked = false;
    label.append(input, doc.createTextNode(text)); return input;
  };
  const details = (label, value) => {
    const section = add("details", ""); add("summary", label, section); add("pre", value || "无", section);
  };
  let context, fallback;
  if (preview.context_available) {
    details(`查看实际页面上下文摘录（${[...preview.context_excerpt].length} 字符，最多 4,000 字符）`, preview.context_excerpt);
    context = check("allowModelPageContext", "仅本次同意发送上方页面上下文摘录，用于辅助理解视频；不是页面全文许可");
  }
  if (preview.fallback_available || textTask) {
    details("查看采集的页面文本（发送前清理播放器界面，并按本次许可的上限截取）", preview.captured_page_text);
    details("查看浏览器字幕线索（未经媒体校验）", preview.captured_subtitles);
  }
  if (preview.fallback_available) {
    fallback = check("allowPageTextFallback", `仅本次同意：视频获取失败时，可改用页面全文（最多 ${preview.page_text_limit.toLocaleString()} 字符）和浏览器字幕线索（最多 ${preview.subtitle_text_limit.toLocaleString()} 字符）发送给上述模型。未同意则停止并保留本机资料`);
  }
  const consent = check("modelDataConsent", "我已审阅上述接收方、标题、链接和所选资料，同意本次任务发送，可能产生费用");
  const status = add("p", ""); status.setAttribute("role", "status");
  const footer = add("footer", ""), cancel = add("button", "取消", footer), send = add("button", "同意并开始", footer);
  cancel.type = send.type = "button"; send.className = "primary"; send.disabled = true;
  consent.onchange = () => { send.disabled = !consent.checked; };
  return new Promise(resolve => {
    let finished = false;
    const finish = value => {
      if (finished) return; finished = true;
      events.removeEventListener("learnnote:navigation", cancelled);
      dialog.close(); dialog.remove(); resolve(value);
    };
    const cancelled = () => finish(null);
    cancel.onclick = cancelled;
    dialog.addEventListener("cancel", event => { event.preventDefault(); cancelled(); });
    dialog.addEventListener("close", cancelled);
    events.addEventListener("learnnote:navigation", cancelled);
    send.onclick = () => {
      if (!consent.checked || finished) return;
      let current = false;
      try { current = isCurrent(); } catch {}
      if (!current) { status.textContent = "任务或模型设置已改变，请取消后重新审阅。"; send.disabled = true; return; }
      finish({ allow_model_page_context: Boolean(context?.checked), allow_page_text_fallback: Boolean(fallback?.checked), review_fingerprint: preview.fingerprint });
    };
    doc.body.append(dialog); dialog.showModal();
    dialog.scrollTop = 0; heading.focus({ preventScroll: true });
  });
}
