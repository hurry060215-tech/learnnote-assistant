// Cached recognizer scores are provenance, never factual verification.
export function canOcrMaterial(material) {
  return Boolean(material?.kind === "material" && material.source_type === "pdf" &&
    (material.status === "ocr_required" || material.status === "ocr_partial" || material.metadata?.ocr_performed));
}

function confidence(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1
    ? `${Math.round(value * 100)}%` : "未知";
}

export function mountMaterialOcr(container, { material, api, isCurrent = () => true, onUpdated = async () => {} }) {
  if (!canOcrMaterial(material)) return null;
  const root = document.createElement("section");
  root.className = "material-ocr-panel ocr-frame";
  root.setAttribute("aria-label", "扫描 PDF 本地 OCR");
  const heading = document.createElement("h2"); heading.textContent = "扫描 PDF · 本地 OCR · 未核验";
  const hint = document.createElement("p");
  hint.textContent = "置信度是识别器对文字的评分，不代表事实已经核验；缺少评分时显示未知。请对照原始 PDF。";
  const progress = document.createElement("p"); progress.setAttribute("role", "status"); progress.textContent = "正在读取已保存的 OCR…";
  const original = document.createElement("a"); original.textContent = "打开原始 PDF 核对";
  const endpoint = `/api/library/materials/${encodeURIComponent(material.id || material.material_id)}`;
  original.className = "tool-link"; original.href = `${endpoint}/source`; original.target = "_blank"; original.rel = "noopener";
  const run = document.createElement("button"); run.type = "button"; run.textContent = "开始本地 OCR（每次最多 24 页）"; run.disabled = true;
  const pages = document.createElement("div"); pages.className = "material-ocr-pages source-picker";
  root.append(heading, hint, progress, original, run, pages); container.prepend(root);
  const active = () => root.isConnected && isCurrent();
  let busy = false, cached = null;
  function render(value) {
    cached = value;
    const count = Number(value.processed_page_count || 0), total = Number(value.page_count || 0);
    progress.textContent = value.warning || `已保存 ${count} / ${total} 页 OCR；未核验。`;
    run.hidden = value.status === "ready";
    run.textContent = count ? "继续识别未完成页面（每次最多 24 页）" : "开始本地 OCR（每次最多 24 页）";
    pages.replaceChildren();
    for (const page of value.pages || []) {
      const details = document.createElement("details"), summary = document.createElement("summary");
      summary.textContent = `第 ${page.page} 页 · 识别器平均置信度 ${confidence(page.confidence)} · 未核验`;
      details.append(summary);
      // Keep large scans light: line elements are created on explicit expansion.
      details.addEventListener("toggle", () => {
        if (!details.open || details.dataset.loaded) return;
        details.dataset.loaded = "true";
        for (const line of page.lines || []) {
          const text = document.createElement("p"), score = document.createElement("small");
          text.textContent = line.text || "";
          score.textContent = `识别器置信度 ${confidence(line.confidence)} · 未核验`;
          text.append(score); details.append(text);
        }
        if (!page.lines?.length) {
          const text = document.createElement("p");
          text.textContent = page.text ? `${page.text}（未保存逐行评分）` : "本页未识别到文字；可对照原始 PDF 核对。";
          details.append(text);
        }
      });
      pages.append(details);
    }
  }
  async function load() {
    try {
      const result = await api(`${endpoint}/ocr`);
      if (!active()) return;
      render(result.ocr); run.disabled = false;
    } catch (error) {
      if (active()) progress.textContent = error.message;
    }
  }
  run.addEventListener("click", async () => {
    if (busy || run.disabled || !active()) return;
    if (!confirm("使用本机可选 OCR 继续识别扫描 PDF？每次最多 24 页，仅处理尚未完成的页面；识别结果会标为未核验。")) return;
    busy = true; run.disabled = true;
    progress.textContent = "正在本机识别这一批页面；已保存的结果仍可查看。";
    try {
      const result = await api(`${endpoint}/ocr`, { method: "POST" });
      if (!active()) return;
      render(result.ocr);
      await onUpdated(result.material);
    } catch (error) {
      if (active()) {
        if (cached) render(cached);
        progress.textContent = `${error.message} 已保存的 OCR 结果仍保留，可以重试。`;
      }
    } finally {
      busy = false;
      if (active()) run.disabled = false;
    }
  });
  const ready = load();
  return { root, ready };
}
