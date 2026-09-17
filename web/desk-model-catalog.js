import { api } from "/web/desk-api.js";

export function installModelCatalog(state) {
  const $ = id => document.getElementById(id);
  const panel = document.createElement("div");
  panel.className = "model-catalog";
  panel.innerHTML = '<label for="modelChoice">选择具体模型</label><select id="modelChoice"><option value="">同步模型列表后选择，也可填写下方模型 ID</option></select><p id="modelCapabilityInfo" class="muted" role="status">模型是否支持图片，需要按具体型号确认。</p><button id="testVisionModel" type="button">测试图片识别</button><p class="muted">图片测试只发送程序生成的红蓝色块，不上传笔记或视频。更换模型后请保存连接。</p>';
  document.querySelector('label[for="model"]').before(panel);
  $("discoverModelList").textContent = "同步可用模型";
  let details = [], epoch = 0;
  const cacheKey = "learnnote.model.catalog";
  const scope = () => $("provider").value + "|" + $("baseUrl").value.trim().replace(/\/$/, "");
  const readCache = () => { try { return JSON.parse(localStorage.getItem(cacheKey) || "{}"); } catch { return {}; } };
  function describe() {
    const item = details.find(row => row.id === $("model").value);
    $("modelChoice").value = item?.id || "";
    $("modelCapabilityInfo").textContent = item ? `${item.id} · ${item.capability_label || "视觉能力待测试"}` : "尚未读取当前型号的能力信息；可同步模型列表或进行图片测试。文字连接测试不代表可以读图。";
  }
  function render(rows, cached = false) {
    details = rows;
    const select = $("modelChoice");
    select.replaceChildren(Object.assign(document.createElement("option"), {value:"",textContent:"选择模型，或在下方输入模型 ID"}), ...rows.map(row => Object.assign(document.createElement("option"), {value:row.id,textContent:`${row.id} · ${row.capability_label || "视觉待测试"}`})));
    $("availableModels").replaceChildren(...rows.map(row => Object.assign(document.createElement("option"), {value:row.id,label:row.capability_label || ""})));
    describe();
    if (cached && rows.length) $("modelCapabilityInfo").textContent += " · 上次读取的列表，可同步刷新";
  }
  function reset() { epoch++; const cached = readCache()[scope()]; render(Array.isArray(cached?.models) && Date.now() - cached.at < 86400000 ? cached.models : [], true); }
  function remember(key, rows) {
    const cache = readCache(); cache[key] = {at:Date.now(),models:rows};
    try { localStorage.setItem(cacheKey,JSON.stringify(Object.fromEntries(Object.entries(cache).sort((a,b)=>b[1].at-a[1].at).slice(0,12)))); } catch {}
  }
  function payload(mode) {
    return {provider:$("provider").value,base_url:$("baseUrl").value.trim(),model:$("model").value.trim() || "auto",api_key:$("apiKey").value,use_saved_connection:Boolean(state.model.use_saved_connection) && $("baseUrl").value.trim() === state.model.base_url && !$("apiKey").value.trim(),mode};
  }
  $("provider").addEventListener("change",reset);
  $("baseUrl").addEventListener("input",reset);
  $("apiKey").addEventListener("input",() => {epoch++;});
  $("model").addEventListener("input",describe);
  $("modelChoice").onchange = () => { if (!$("modelChoice").value) return; $("model").value = $("modelChoice").value; $("model").dispatchEvent(new Event("input",{bubbles:true})); };
  $("discoverModelList").onclick = async () => {
    const button = $("discoverModelList"), id = ++epoch, key = scope();
    button.disabled = true; $("settingsStatus").textContent = "正在向当前服务读取可用模型…";
    try {
      const result = await api("/api/model/setup/check", {method:"POST",body:JSON.stringify(payload("models"))});
      if (id !== epoch || key !== scope()) return;
      if (!result.ok) throw new Error(result.message || "模型列表读取失败");
      const rows = result.model_details || (result.models || []).map(id => ({id})); render(rows);
      remember(key, rows);
      $("settingsStatus").textContent = `${result.message} 选择模型后保存；旧的自定义模型不会被自动替换。`;
    } catch(error) { if(id === epoch) $("settingsStatus").textContent = error.message; }
    finally { button.disabled = false; }
  };
  $("testVisionModel").onclick = async () => {
    if (!$("model").value.trim()) { $("settingsStatus").textContent = "请先选择或填写具体模型。"; return; }
    const button = $("testVisionModel"), selected = payload("vision"), key = scope(), id = ++epoch;
    button.disabled = true; $("settingsStatus").textContent = "正在测试图片输入与识别…";
    try {
      const result = await api("/api/model/setup/check",{method:"POST",body:JSON.stringify(selected)});
      if(id !== epoch || key !== scope() || selected.model !== $("model").value.trim()) return;
      $("settingsStatus").textContent = result.message;
      if(result.ok) { details = details.filter(item=>item.id !== selected.model); details.push({id:selected.model,vision:true,capability_source:"image_test",capability_label:"图片识别已实测"}); render(details); remember(key, details); }
    } catch(error) { if(id === epoch) $("settingsStatus").textContent = error.message; }
    finally { button.disabled = false; }
  };
  $("settings").addEventListener("click",reset);
  reset();
}
