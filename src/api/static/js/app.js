(function () {
  let runId = null;
  let progressTimer = null;
  let groundTruth = null;
  async function postJson(url, payload, target) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "Accept": "text/html", "HX-Request": "true"},
      body: JSON.stringify(payload)
    });
    const fragment = await response.text();
    htmx.swap(target, fragment, {swapStyle: "outerHTML"});
    if (!response.ok) {
      throw new Error(`request failed with status ${response.status}`);
    }
  }

  async function loadJsonFile(file) {
    if (file.size > 5 * 1024 * 1024) {
      throw new Error("文件超过 5 MiB");
    }
    return JSON.parse(await file.text());
  }

  function renderChart(element, option) {
    const chart = echarts.init(element);
    chart.setOption(option);
    return chart;
  }

  function show(id, html) { document.getElementById(id).innerHTML = html; }
  function requestId() { return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()); }

  async function startRun() {
    const error = document.getElementById("form-error"); const button = document.getElementById("start-run"); error.textContent = "";
    const file = document.getElementById("records-file").files[0];
    if (!file) { error.textContent = "请先选择客服回复 JSON 文件。"; return; }
    if (!document.getElementById("external-ack").checked) { error.textContent = "请确认外部处理授权。"; return; }
    let records;
    try { records = await loadJsonFile(file); } catch (e) { error.textContent = `文件读取失败：${e.message}`; return; }
    if (!Array.isArray(records)) { error.textContent = "JSON 顶层必须是数组。"; return; }
    button.disabled = true; button.textContent = "正在提交…";
    let response;
    try {
      response = await fetch("/runs", {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}, body: JSON.stringify({request_id: requestId(), records, manual_review_enabled: document.getElementById("manual-review").checked, external_processing_acknowledged: true})});
    } catch (e) { error.textContent = `无法连接后端：${e.message}`; button.disabled = false; button.textContent = "创建检测运行"; return; }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) { error.textContent = payload.detail || "创建运行失败，请检查后端日志和 LLM 配置"; button.disabled = false; button.textContent = "创建检测运行"; return; }
    runId = payload.data && payload.data.run_id ? payload.data.run_id : requestId();
    show("run-summary", `<h2>运行摘要</h2><p><strong>${runId}</strong></p><p>${records.length} 条记录已提交</p><button class="secondary" id="refresh-run" type="button">刷新进度</button>`);
    show("progress", `<h2>检测进度</h2><p>运行已创建，等待检测器处理。</p><progress max="100" value="0"></progress>`);
    document.getElementById("export-links").innerHTML = ["predictions.json", "evaluation.json", "report.md"].map(a => `<a href="/runs/${runId}/downloads/${a}">${a}</a>`).join(" ");
    const truthFile = document.getElementById("ground-truth-file").files[0];
    if (truthFile) { try { groundTruth = await loadJsonFile(truthFile); } catch (e) { error.textContent = `官方标注读取失败：${e.message}`; } }
    document.getElementById("refresh-run").onclick = refreshRun;
    button.textContent = "已提交";
    if (progressTimer) clearInterval(progressTimer);
    progressTimer = setInterval(async () => {
      await refreshRun();
      const text = document.getElementById("progress").textContent;
      if (text.includes("frozen") || text.includes("retryable_partial") || text.includes("abandoned")) {
        clearInterval(progressTimer); progressTimer = null;
      }
    }, 2000);
  }
  async function refreshRun() {
    if (!runId) return;
    const response = await fetch(`/runs/${runId}/progress`, {headers: {"Accept": "application/json"}});
    const payload = await response.json();
    const data = payload.data || {};
    const completed = data.completed ?? data.completed_count ?? 0;
    const total = data.total ?? data.total_count ?? "—";
    show("progress", `<h2>检测进度</h2><p>${completed} / ${total} 条记录</p><progress max="${total || 1}" value="${completed}"></progress>`);
    if (data.state === "frozen" || data.state === "retryable_partial") {
      if (data.state === "frozen" && groundTruth) {
        await fetch(`/runs/${runId}/ground-truth`, {method:"POST", headers:{"Content-Type":"application/json", "Accept":"application/json"}, body:JSON.stringify({request_id:requestId(), records:groundTruth})});
        const evaluation = await fetch(`/runs/${runId}/evaluation`, {method:"POST", headers:{"Content-Type":"application/json", "Accept":"application/json"}, body:JSON.stringify({request_id:requestId()})});
        if (evaluation.ok) show("evaluation", `<h2>评测指标</h2><pre>${escapeHtml(JSON.stringify((await evaluation.json()).data, null, 2))}</pre>`);
      }
      const resultResponse = await fetch(`/runs/${runId}/results`, {headers: {"Accept": "application/json"}});
      if (resultResponse.ok) {
        const resultPayload = await resultResponse.json();
        const results = resultPayload.data?.results || [];
        show("results", `<h2>检测结果</h2><p>共 ${results.length} 条记录</p><div class="table-wrap"><table><thead><tr><th>记录</th><th>状态</th><th>详情</th></tr></thead><tbody>${results.map(item => `<tr><td>${item.id}</td><td>${item.kind}</td><td><code>${escapeHtml(JSON.stringify(item.result || item.error_summary || ""))}</code></td></tr>`).join("")}</tbody></table></div>`);
      }
    }
  }
  function escapeHtml(value) { return String(value).replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char])); }
  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("records-file").addEventListener("change", async e => {
      const file = e.target.files[0]; document.getElementById("records-name").textContent = file ? `${file.name}（已选择，点击创建检测运行后上传）` : "尚未选择文件";
      if (!file) return;
      try { const records = await loadJsonFile(file); if (!Array.isArray(records)) throw new Error("JSON 顶层必须是数组"); document.getElementById("records-name").textContent = `${file.name}（${records.length} 条记录，待上传）`; }
      catch (error) { document.getElementById("form-error").textContent = `文件读取失败：${error.message}`; }
    });
    document.getElementById("ground-truth-file").addEventListener("change", e => { document.getElementById("ground-truth-name").textContent = e.target.files[0]?.name || "尚未选择文件"; });
    document.getElementById("start-run").addEventListener("click", startRun);
  });

  window.Dashboard = {postJson, loadJsonFile, renderChart, startRun, refreshRun};
})();
