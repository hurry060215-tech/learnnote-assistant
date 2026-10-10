// Existing strong warning nodes are presentation data, never tool instructions.
export function collapseSourceReviews(root) {
  const markers = [...root.querySelectorAll("strong")].filter(node =>
    node.textContent === "【待核对：仅定位到来源】" && !node.closest("pre,code,blockquote,a,h1,h2,h3,h4,h5,h6,[data-source-reviews]"));
  if (!markers.length) return;
  const details = document.createElement("details"), summary = document.createElement("summary");
  details.dataset.sourceReviews = "";
  details.className = "source-review-panel";
  summary.textContent = `来源核对 · ${markers.length} 条定位提示`;
  const explanation = document.createElement("p");
  explanation.textContent = "以下表述只找到了候选来源位置，尚未验证来源是否支持结论。请打开对应出处核对；这些提示未被判定为已验证。";
  details.append(summary, explanation);
  for (const [index, marker] of markers.entries()) {
    const number = index + 1, item = document.createElement("section"), label = document.createElement("strong");
    item.id = `source-review-${number}`;
    label.textContent = `来源核对 ${number} · 尚未验证支持`;
    const excerpt = document.createElement("p");
    // Keep the rendered source links/formatting adjacent to this exact marker.
    // Another marker ends this excerpt; do not guess a different statement.
    for (let node = marker.nextSibling; node; node = node.nextSibling) {
      if (node.nodeType === 1 && node.matches("strong") && node.textContent === "【待核对：仅定位到来源】") break;
      excerpt.append(node.cloneNode(true));
    }
    if (!excerpt.textContent.trim()) excerpt.textContent = "该提示后没有正文，请回到原笔记核对。";
    item.append(label, excerpt);
    details.append(item);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "time-link source-review-link";
    button.textContent = `来源 ${number}`;
    button.title = "仅定位到来源，尚未验证支持；展开核对记录";
    button.setAttribute("aria-controls", item.id);
    button.onclick = () => {
      details.open = true;
      item.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    };
    marker.replaceWith(button);
  }
  root.append(details);
}
