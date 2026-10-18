// A local action record for one whole rendered edition. This controller is not
// exposed to the assistant and never infers a review from reading or navigation.
const labels = {
  unmarked: "尚未记录个人核对", current: "本人已核对", stale: "核对记录已过期",
  revoked: "已撤销个人核对", imported: "导入的核对记录 · 待重新核对",
};

export function personalReviewView(value, renderedRevision) {
  const valid = value && Object.hasOwn(labels, value.status) && typeof value.review_revision === "string";
  if (!valid) return { label: "核对记录暂不可用", mark: false, revoke: false, mismatch: false };
  const mismatch = !renderedRevision || value.note_revision !== renderedRevision;
  return {
    label: mismatch && value.status === "current" ? "笔记版本已变化 · 请刷新正文" : labels[value.status],
    mark: !mismatch && value.can_mark === true && Boolean(value.context_revision) && value.status !== "current",
    revoke: ["current", "stale", "imported"].includes(value.status), mismatch,
  };
}

export function installPersonalReview({ state, api, refreshNote, document: doc = document,
  events = window, requestId = () => crypto.randomUUID() }) {
  const reader = doc.getElementById("document"), host = doc.createElement("section");
  host.id = "personalReview"; host.className = "personal-review"; host.hidden = true;
  host.setAttribute("aria-labelledby", "personalReviewHeading");
  host.innerHTML = '<details id="personalReviewDetails"><summary><span id="personalReviewHeading">个人核对</span><span id="personalReviewState" role="status"></span><span class="personal-review-disclosure">详情与操作</span></summary><div class="personal-review-body"><p class="muted personal-review-scope">当前整篇笔记 · 本机个人核对</p><p id="personalReviewSources" class="muted"></p><p class="muted">只记录本机核对动作，不验证身份。原有不确定性提示仍然适用。</p><div class="personal-review-actions"><button id="markPersonalReview" class="primary" type="button">我已核对当前整篇笔记</button><button id="revokePersonalReview" type="button" hidden>撤销核对</button><button id="refreshPersonalReview" type="button">刷新核对状态</button></div></div></details><p class="muted personal-review-boundary">个人操作记录，不代表内容已被证实。</p><p id="personalReviewFeedback" class="muted" aria-live="polite" hidden></p>';
  reader.after(host);
  const $ = id => host.querySelector(`#${id}`), mark = $("markPersonalReview"), revoke = $("revokePersonalReview");
  const refresh = $("refreshPersonalReview"), status = $("personalReviewState"), sources = $("personalReviewSources"), feedback = $("personalReviewFeedback");
  let sequence = 0, value = null, owner = null, busy = false, loading = false;
  function snapshot() {
    if (!state.selected || state.editing || state.readerSnapshot || reader.querySelector("[data-progressive-reader]")
        || reader.dataset.readerSource !== `${state.selected.kind}:${state.selected.id}`
        || reader.dataset.sourceRevision !== state.revision) return null;
    return { kind: state.selected.kind, id: state.selected.id, epoch: state.epoch,
      revision: state.revision, renderedRevision: reader.dataset.sourceRevision };
  }
  const same = (a, b) => a && b && ["kind", "id", "epoch", "revision", "renderedRevision"].every(key => a[key] === b[key]);
  const current = (token, selected) => token === sequence && same(selected, snapshot());
  const endpoint = selected => `/api/tasks/editions/${selected.kind}/${encodeURIComponent(selected.id)}/personal-review`;
  function message(text) { feedback.textContent = text; feedback.hidden = !text; }
  function draw() {
    const selected = snapshot(), view = personalReviewView(value, selected?.renderedRevision);
    status.textContent = value ? view.label : loading ? "正在读取核对记录…" : "核对记录暂不可用";
    host.dataset.status = value?.status === "current" && view.mismatch ? "mismatch" : value?.status || "unavailable";
    const scope = value?.scope_detail || (value?.source_scope === "reading_only" ? "仅有当前可读正文；没有可核对的本机来源。" : "");
    const sourceLabels = Array.isArray(value?.source_labels) ? value.source_labels.filter(label => typeof label === "string").join("、") : "";
    const checked = value?.checked_at ? new Date(value.checked_at) : null;
    sources.textContent = [scope, sourceLabels ? `本机来源：${sourceLabels}` : "",
      checked && Number.isFinite(checked.getTime()) ? `记录时间：${checked.toLocaleString()}` : ""].filter(Boolean).join(" · ");
    sources.hidden = !sources.textContent;
    mark.disabled = busy || loading || !same(owner, selected) || !view.mark;
    mark.textContent = value?.status === "stale" || value?.status === "imported" ? "重新核对并记录" : "我已核对当前整篇笔记";
    revoke.hidden = !view.revoke;
    revoke.disabled = busy || loading || !same(owner, selected) || !view.revoke;
    refresh.disabled = busy || loading;
    refresh.textContent = view.mismatch ? "刷新正文与核对状态" : "刷新核对状态";
    host.setAttribute("aria-busy", String(busy || loading));
  }
  function reset() {
    sequence++; value = owner = null; busy = loading = false; host.hidden = true; $("personalReviewDetails").open = false; message(""); draw();
  }
  async function load({ explanation = "" } = {}) {
    if (busy) return;
    const selected = snapshot();
    if (!selected) { reset(); return; }
    const token = ++sequence;
    const changed = !same(owner, selected);
    if (changed) { value = null; $("personalReviewDetails").open = false; }
    owner = selected; loading = true; host.hidden = false;
    if (explanation || changed) message(explanation);
    draw();
    try {
      const result = await api(endpoint(selected));
      if (!current(token, selected)) return;
      value = result;
      if (!Object.hasOwn(labels, result?.status || "") || typeof result?.review_revision !== "string") throw new Error("invalid_personal_review");
      if (personalReviewView(value, selected.renderedRevision).mismatch && !explanation && !feedback.textContent)
        message("当前显示的正文与本机版本不一致。请先刷新正文，再明确核对；已有记录仍可撤销。");
    } catch {
      if (!current(token, selected)) return;
      value = null;
      message(explanation ? `${explanation} 核对记录暂不可读取，请稍后刷新。` : "核对记录暂不可读取，请稍后刷新。未更改正文或核对记录。");
    } finally {
      if (current(token, selected)) { loading = false; draw(); }
    }
  }
  async function act(action) {
    const selected = snapshot(), view = personalReviewView(value, selected?.renderedRevision);
    if (busy || loading || !same(owner, selected) || !(action === "mark" ? view.mark : view.revoke)) return;
    const token = ++sequence;
    busy = true; message(action === "mark" ? "正在记录个人核对…" : "正在撤销核对…"); draw();
    try {
      const result = await api(endpoint(selected), { method: "POST", body: JSON.stringify({
        action, expected_context_revision: value.context_revision || "",
        expected_review_revision: value.review_revision, request_id: requestId(),
      }) });
      if (!current(token, selected)) return;
      value = result;
      message(action === "mark" ? "已读取本机最新核对记录。只适用于记录时的整篇笔记与来源版本。" : "已读取本机最新记录；撤销不会修改正文或来源。");
    } catch (error) {
      if (!current(token, selected)) return;
      busy = false;
      await load({ explanation: error.status === 409
        ? "笔记、来源或核对记录已变化，本次操作未应用。已重新读取状态；请核对最新内容后再明确点击。"
        : "未能确认操作结果，已重新读取本机记录。请检查状态后再操作。" });
    } finally {
      if (current(token, selected)) { busy = false; draw(); }
    }
  }
  mark.onclick = () => act("mark"); revoke.onclick = () => act("revoke");
  refresh.onclick = async () => {
    const selected = snapshot();
    if (busy || loading || !selected) return;
    if (personalReviewView(value, selected.renderedRevision).mismatch) {
      reset();
      try { await refreshNote(); }
      catch { if (same(selected, snapshot())) await load({ explanation: "正文暂不可刷新。已有记录保留，请稍后重试。" }); }
    } else { message(""); await load(); }
  };
  events.addEventListener("learnnote:selection", reset);
  // renderEditionStable records the reader's source after dispatching this event.
  events.addEventListener("learnnote:document", () => { queueMicrotask(() => load()); });
  return { load, reset };
}
