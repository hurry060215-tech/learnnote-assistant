// A bounded, sequential queue. Raw File objects go to the existing local APIs;
// only their hash-backed responses establish deduplication, never file metadata.
export const IMPORT_LIMITS = { count: 20, documentBytes: 32 * 1024 ** 2, totalBytes: 4 * 1024 ** 3 };
const documentPattern = /\.(pdf|md|markdown|txt|html?)$/i;
const videoPattern = /\.(mp4|m4s|m4v|mov|mkv|webm|flv|avi)$/i;
const videoMime = /^(video\/(mp4|x-m4v|quicktime|x-matroska|webm|x-flv|avi|x-msvideo))$/i;
export const importKind = file => documentPattern.test(file.name) ? "material"
  : videoPattern.test(file.name) || (!/\.[^.]+$/.test(file.name) && videoMime.test(file.type)) ? "task" : "";
export const importSize = bytes => `${(Number(bytes) / 1024 ** 2).toFixed(2)} MiB`;

export function previewVideoFile(file, { signal } = {}) {
  return new Promise(resolve => {
    const video = document.createElement("video"), url = URL.createObjectURL(file);
    let timer, finished = false;
    const finish = duration => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", aborted);
      video.onloadedmetadata = null; video.onerror = null;
      URL.revokeObjectURL(url); video.removeAttribute("src"); video.load();
      resolve({ duration: Number.isFinite(duration) && duration > 0 ? duration : null });
    };
    const aborted = () => finish(null);
    signal?.addEventListener("abort", aborted, { once: true });
    if (signal?.aborted) { finish(null); return; }
    timer = setTimeout(() => finish(null), 10000);
    video.preload = "metadata";
    video.onloadedmetadata = () => finish(video.duration);
    video.onerror = () => finish(null);
    video.src = url;
  });
}

export function createMaterialBatch({ api, changed = () => {}, previewVideo = previewVideoFile, videoLimit = () => IMPORT_LIMITS.totalBytes }) {
  let items = [], generation = 0, preparing = false, running = false, stopped = false;
  let message = "", controller = null, snapshot = null;
  const emit = () => changed();
  const queue = {
    get items() { return items; }, get preparing() { return preparing; }, get running() { return running; },
    get message() { return message; }, get snapshot() { return snapshot; }, get stopped() { return stopped; },
    get canSubmit() { return !preparing && !running && items.some(item => item.preview && ["ready", "failed"].includes(item.status)); },
    select(files, encoding = "") {
      if (running) return false;
      queue.cancel(); generation++; snapshot = null; message = ""; stopped = false;
      const selected = Array.from(files || []);
      if (selected.length > IMPORT_LIMITS.count || selected.reduce((sum, file) => sum + file.size, 0) > IMPORT_LIMITS.totalBytes) {
        items = []; message = "每批最多 20 个文件、合计 4 GiB。请减少所选文件后重试。"; emit(); return false;
      }
      items = selected.map(file => {
        const kind = importKind(file), max = kind === "material" ? IMPORT_LIMITS.documentBytes : Number(videoLimit()) || IMPORT_LIMITS.totalBytes;
        const error = !kind ? "不支持此类型，请选择 PDF、Markdown、TXT、HTML 或支持的视频。"
          : !Number.isSafeInteger(file.size) || file.size <= 0 ? "文件为空或大小无效。"
            : file.size > max ? `文件超过 ${importSize(max)} 上限，请拆分后再导入。` : "";
        return { file, kind, encoding: kind === "material" && !/\.pdf$/i.test(file.name) ? encoding : "",
          status: error ? "invalid" : "pending", detail: error, preview: null, result: null };
      });
      emit(); return true;
    },
    async prepare() {
      if (preparing || running) return;
      const token = generation;
      preparing = true; stopped = false; message = "正在逐个本地预检，尚未导入。"; emit();
      try {
        for (const item of items) {
          if (token !== generation || stopped) break;
          if (item.preview || !["pending", "failed"].includes(item.status)) continue;
          item.status = "preflighting"; item.detail = "正在本地预检…"; emit();
          controller = new AbortController();
          try {
            let result;
            if (item.kind === "material") {
              const data = new FormData(); data.append("file", item.file); data.append("encoding", item.encoding);
              result = await api("/api/library/materials/preview", { method: "POST", body: data, signal: controller.signal });
            } else {
              result = await previewVideo(item.file, { signal: controller.signal });
              if (token !== generation || stopped) break;
              if (!Number.isFinite(result?.duration) || result.duration <= 0) {
                item.detail = "浏览器无法读取时长，正在上传到本机校验并暂存；不调用模型…"; emit();
                const data = new FormData(); data.append("file", item.file);
                result = await api("/api/media/preflight-local", { method: "POST", body: data, signal: controller.signal });
                if (!Number.isFinite(result?.duration) || result.duration <= 0 || !/^[a-f0-9]{32}$/.test(result?.staging_token || ""))
                  throw new Error("本机未返回有效的时长与暂存结果，请重新预检未完成项。");
              }
            }
            if (token !== generation || stopped) break;
            item.preview = result; item.status = "ready"; item.detail = "预检完成，待提交。";
          } catch (error) {
            if (token !== generation || stopped) break;
            item.status = "failed"; item.detail = error.message || "预检失败，请重试。";
          }
          emit();
        }
      } finally {
        if (token === generation) {
          controller = null; preparing = false;
          message = stopped ? "已停止预检，尚未提交的文件保留在列表中。" : "预检完成。确认文件和处理路线后再提交；预检失败的文件不会导入。";
          emit();
        }
      }
    },
    cancel() {
      if (!preparing && !running && !items.length) return;
      stopped = true;
      if (preparing) {
        generation++; controller?.abort(); controller = null; preparing = false;
        for (const item of items) if (item.status === "preflighting") { item.status = "pending"; item.detail = "预检已停止。"; }
      }
      message = running ? "已停止后续提交，正在等待已提交文件的结果；完成的资料会保留。" : "已停止，完成的资料会保留；可继续未提交或失败的文件。";
      emit();
    },
    async submit(options, route = "", current = () => true) {
      if (!queue.canSubmit) return [];
      // Keep a private copy for every retry, including after an uncertain network
      // response. Changing a model/encoding cannot silently broaden this batch.
      snapshot ||= { options: JSON.parse(JSON.stringify(options || {})), route };
      running = true; stopped = false; message = "正在逐个提交。停止只影响尚未提交的文件。"; emit();
      const completed = [];
      try {
        for (const item of items) {
          if (stopped || !current()) { stopped = true; break; }
          if (!item.preview || !["ready", "failed"].includes(item.status)) continue;
          item.status = "submitting"; item.detail = "正在提交，关闭窗口不会撤回此文件。"; emit();
          const data = new FormData(), stagingToken = item.kind === "task" && item.preview.staging_token;
          if (stagingToken) data.append("staging_token", stagingToken);
          else data.append("file", item.file);
          if (item.kind === "material") data.append("encoding", item.encoding);
          else data.append("options", JSON.stringify(snapshot.options));
          try {
            const result = await api(item.kind === "material" ? "/api/library/materials/import" : "/api/tasks/from-local", { method: "POST", body: data });
            if (!(item.kind === "material" ? result?.material?.material_id : result?.task_id)) throw new Error("未收到有效结果，请重试并由本机内容哈希核对已有资料。");
            item.result = result; item.status = "success";
            const reused = result.deduplicated || result.material?.deduplicated;
            item.detail = reused ? "内容哈希相同，已复用现有结果。" : item.kind === "task" ? "已建立视频任务，后续处理进度见任务。" : "已导入，原始文件保留在本机。";
            if (item.kind === "material" && reused && item.encoding && String(result.material.metadata?.encoding || "").toLowerCase() !== item.encoding.toLowerCase())
              item.detail += ` 原资料编码为 ${result.material.metadata?.encoding || "未知"}，本次没有覆盖；请在资料中重新选择编码。`;
            completed.push(item);
          } catch (error) {
            item.status = "failed"; item.detail = `${error.message || "提交失败"} 可重试；本机将按原始内容核对重复结果。`;
            if (stagingToken) {
              if (error.status === 404 && error.code === "staging_token_not_found") {
                if (item.submissionUncertain) {
                  // The token may have been consumed by a successful create whose
                  // response was lost. Hash dedup excludes failed/cancelled tasks,
                  // so uploading again cannot safely resolve this uncertainty.
                  item.status = "unconfirmed";
                  item.detail = "提交结果待核对，暂存文件已被使用或过期。请关闭此窗口，在资料库按文件名核对视频任务（包括失败或取消的任务）；为避免重复任务，不会自动重新上传。";
                } else {
                  item.preview = null;
                  item.detail = "暂存文件已过期或不可用。原始文件仍保留，请点击「重新预检未完成项」重新在本机校验，再按本批原设置提交。";
                }
              } else {
                item.submissionUncertain ||= !error.status || error.status >= 500 || error.status === 408;
                if (item.submissionUncertain) item.detail = "未能确认视频任务是否已建立。可重试同一次暂存提交；不会重新上传。若暂存已被使用，将提示到资料库核对。";
              }
            }
          }
          emit();
        }
      } finally {
        running = false;
        const count = items.filter(item => item.status === "success").length;
        message = `${stopped ? "已停止后续提交。" : "本轮提交结束。"}已完成 ${count} / ${items.length} 项；完成项会保留且不会再次提交。`;
        emit();
      }
      return completed;
    },
  };
  return queue;
}

// Display the same options the queue will submit. Do not send credentials or
// filenames to a remote route planner merely to explain the local selection.
export function batchVideoRoute(options, health = {}, { localFile = true } = {}) {
  if (options.content_mode === "subtitles") return `视频：仅提取${localFile ? "内嵌" : "可用"}字幕，不调用转写或总结模型；没有字幕时停止。${localFile ? "" : "来源站点仍需联网。"}`;
  let host = "当前配置的服务";
  try { host = new URL(options.llm_base_url || health.default_llm_base_url).host; } catch {}
  const model = options.llm_model || health.default_llm_model || "尚未配置";
  const transcriber = String(options.transcriber || "").trim().toLowerCase();
  const remoteAsr = ["openai", "openai-compatible", "openai-compatible-asr", "groq", "groq-asr"].includes(transcriber);
  // All compatible ASR choices, including Groq, use the same llm_base_url
  // as text generation. Display only its parsed host, never URL credentials.
  return `视频：优先${localFile ? "内嵌" : "可用"}字幕；没有字幕时${remoteAsr ? `将音频发送到 ${host} 的音频转写接口（与文字模型共用地址）` : "在本机转写（模型需准备完成）"}。必要的字幕${options.visual_understanding ? "与选定画面" : ""}、整理要求将交给 ${host} 的 ${model} 模型；本机网关也可能转发。无 Key 时可选择仅提取字幕；不会自动改用远程服务。模型上下文和图片上限未知；费用与耗时区间未知，缺少当前输入、设备与服务商的测量依据。额外缓存空间也尚不能确定。`;
}
