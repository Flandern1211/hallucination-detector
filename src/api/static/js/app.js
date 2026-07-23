(function () {
  let runId = null;
  let progressTimer = null;
  let groundTruth = null;
  let currentResults = null;
  let severityChart = null;
  let typeChart = null;

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

  function show(id, html) {
    document.getElementById(id).innerHTML = html;
  }

  function requestId() {
    return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now());
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, char => ({
      "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
    }[char]));
  }

  // 渲染严重程度分布图表
  function renderSeverityChart(results) {
    const counts = {"高": 0, "中": 0, "低": 0};
    results.forEach(item => {
      if (item.kind === "success" && item.result && item.result.severity) {
        counts[item.result.severity] = (counts[item.result.severity] || 0) + 1;
      }
    });

    const container = document.getElementById("chart-severity");
    if (!container) return;

    if (severityChart) {
      severityChart.dispose();
    }

    severityChart = echarts.init(container);
    severityChart.setOption({
      title: { text: "严重程度分布", left: "center" },
      tooltip: { trigger: "item" },
      legend: { orient: "vertical", left: "left" },
      series: [{
        name: "严重程度",
        type: "pie",
        radius: "50%",
        data: [
          { value: counts["高"], name: "高风险", itemStyle: { color: "#b42318" } },
          { value: counts["中"], name: "中风险", itemStyle: { color: "#f7c948" } },
          { value: counts["低"], name: "低风险", itemStyle: { color: "#176b3a" } }
        ],
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowOffsetX: 0,
            shadowColor: "rgba(0, 0, 0, 0.5)"
          }
        }
      }]
    });
  }

  // 渲染幻觉类型分布图表
  function renderTypeChart(results) {
    const counts = {};
    results.forEach(item => {
      if (item.kind === "success" && item.result && item.result.primary_type) {
        counts[item.result.primary_type] = (counts[item.result.primary_type] || 0) + 1;
      }
    });

    const container = document.getElementById("chart-type");
    if (!container) return;

    if (typeChart) {
      typeChart.dispose();
    }

    typeChart = echarts.init(container);
    const types = Object.keys(counts);
    const values = Object.values(counts);

    typeChart.setOption({
      title: { text: "幻觉类型分布", left: "center" },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: types,
        axisLabel: { rotate: 30, fontSize: 10 }
      },
      yAxis: { type: "value" },
      series: [{
        name: "数量",
        type: "bar",
        data: values,
        itemStyle: { color: "#2374ab" }
      }]
    });
  }

  // 渲染检测结果表格
  function renderResults(results) {
    const successCount = results.filter(r => r.kind === "success").length;
    const failCount = results.filter(r => r.kind === "failure").length;
    const hallucinationCount = results.filter(r => r.kind === "success" && r.result && r.result.is_hallucination).length;

    let html = `
      <h2>检测结果</h2>
      <div class="result-summary">
        <p>共 ${results.length} 条记录：成功 ${successCount} 条，失败 ${failCount} 条，检出幻觉 ${hallucinationCount} 条</p>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>记录ID</th>
              <th>状态</th>
              <th>是否幻觉</th>
              <th>严重程度</th>
              <th>主要类型</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
    `;

    results.forEach(item => {
      const isHallucination = item.result && item.result.is_hallucination;
      const severity = item.result && item.result.severity;
      const primaryType = item.result && item.result.primary_type;

      html += `<tr>
        <td>${escapeHtml(item.id)}</td>
        <td>${item.kind === "success" ? "✓ 成功" : "✗ 失败"}</td>
        <td>${item.kind === "success" ? (isHallucination ? "⚠️ 是" : "✓ 否") : "—"}</td>
        <td>${severity ? `<span class="severity-tag severity-${severity === "高" ? "high" : severity === "中" ? "medium" : "low"}">${severity}</span>` : "—"}</td>
        <td>${primaryType ? `<span class="type-tag">${escapeHtml(primaryType)}</span>` : "—"}</td>
        <td><button class="secondary btn-sm" onclick="window.Dashboard.showDetail('${escapeHtml(item.id)}')">查看详情</button></td>
      </tr>`;
    });

    html += "</tbody></table></div>";
    show("results", html);
  }

  // 显示单条记录详情
  function showDetail(recordId) {
    if (!currentResults) return;
    const item = currentResults.find(r => r.id === recordId);
    if (!item) return;

    const detailHtml = `<pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre>`;
    const modal = document.createElement("div");
    modal.className = "modal-overlay";
    modal.innerHTML = `
      <div class="modal">
        <div class="modal-header">
          <h3>记录详情: ${escapeHtml(recordId)}</h3>
          <button class="secondary" onclick="this.closest('.modal-overlay').remove()">关闭</button>
        </div>
        <div class="modal-content">${detailHtml}</div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.remove();
    });
  }

  // 渲染人工复审界面
  function renderReview(results) {
    const reviewSection = document.getElementById("review");
    if (!reviewSection) return;

    reviewSection.style.display = "block";
    let html = `
      <h2>人工复审</h2>
      <p class="muted">点击"确认正确"或"修正"按钮对检测结果进行复审。</p>
    `;

    const successResults = results.filter(r => r.kind === "success");
    successResults.forEach(item => {
      const isHallucination = item.result && item.result.is_hallucination;
      const severity = item.result && item.result.severity;
      const primaryType = item.result && item.result.primary_type;

      html += `
        <div class="review-item" id="review-${escapeHtml(item.id)}">
          <div class="review-header">
            <span class="review-id">${escapeHtml(item.id)}</span>
            <span class="review-status ${isHallucination ? "hallucination" : "normal"}">
              ${isHallucination ? "⚠️ 幻觉" : "✓ 正常"}
            </span>
          </div>
          <div class="review-detail">
            ${severity ? `<span class="severity-tag severity-${severity === "高" ? "high" : severity === "中" ? "medium" : "low"}">${severity}</span>` : ""}
            ${primaryType ? `<span class="type-tag">${escapeHtml(primaryType)}</span>` : ""}
            <p>${escapeHtml(item.result.summary || "")}</p>
          </div>
          <div class="review-actions">
            <button class="btn-sm btn-confirm" onclick="window.Dashboard.confirmReview('${escapeHtml(item.id)}')">确认正确</button>
            <button class="btn-sm btn-correct" onclick="window.Dashboard.correctReview('${escapeHtml(item.id)}')">修正</button>
          </div>
        </div>
      `;
    });

    show("review-content", html);
  }

  // 确认复审
  async function confirmReview(recordId) {
    if (!runId || !currentResults) return;
    const item = currentResults.find(r => r.id === recordId);
    if (!item) return;

    try {
      const response = await fetch(`/runs/${runId}/records/${recordId}/review`, {
        method: "POST",
        headers: {"Content-Type": "application/json", "Accept": "application/json"},
        body: JSON.stringify({
          request_id: requestId(),
          status: "confirmed_correct",
          source_prediction_hash: "placeholder",
          reviewed_result: item.result
        })
      });

      if (response.ok) {
        const reviewItem = document.getElementById(`review-${recordId}`);
        if (reviewItem) {
          reviewItem.style.borderColor = "#176b3a";
          reviewItem.querySelector(".review-actions").innerHTML = '<span style="color:#176b3a">✓ 已确认</span>';
        }
      } else {
        alert("复审失败: " + (await response.text()));
      }
    } catch (e) {
      alert("复审请求失败: " + e.message);
    }
  }

  // 修正复审
  function correctReview(recordId) {
    if (!runId || !currentResults) return;
    const item = currentResults.find(r => r.id === recordId);
    if (!item) return;

    const modal = document.createElement("div");
    modal.className = "modal-overlay";
    modal.innerHTML = `
      <div class="modal">
        <div class="modal-header">
          <h3>修正记录: ${escapeHtml(recordId)}</h3>
          <button class="secondary" onclick="this.closest('.modal-overlay').remove()">取消</button>
        </div>
        <div class="modal-content">
          <label><input type="checkbox" id="correct-is-hallucination" ${item.result.is_hallucination ? "checked" : ""}> 存在幻觉</label>
          <label>摘要: <input type="text" id="correct-summary" value="${escapeHtml(item.result.summary || "")}"></label>
          <button class="primary" onclick="window.Dashboard.submitCorrection('${escapeHtml(recordId)}')">提交修正</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }

  // 提交修正
  async function submitCorrection(recordId) {
    const isHallucination = document.getElementById("correct-is-hallucination").checked;
    const summary = document.getElementById("correct-summary").value;

    try {
      const response = await fetch(`/runs/${runId}/records/${recordId}/review`, {
        method: "POST",
        headers: {"Content-Type": "application/json", "Accept": "application/json"},
        body: JSON.stringify({
          request_id: requestId(),
          status: "corrected",
          source_prediction_hash: "placeholder",
          reviewed_result: {
            is_hallucination: isHallucination,
            labels: isHallucination ? ["关键遗漏或歪曲"] : [],
            primary_type: isHallucination ? "关键遗漏或歪曲" : null,
            severity: isHallucination ? "中" : null,
            review_required: !isHallucination,
            claims: [],
            omissions: [],
            summary: summary
          }
        })
      });

      if (response.ok) {
        document.querySelector(".modal-overlay").remove();
        const reviewItem = document.getElementById(`review-${recordId}`);
        if (reviewItem) {
          reviewItem.style.borderColor = "#f7c948";
          reviewItem.querySelector(".review-actions").innerHTML = '<span style="color:#856404">✏️ 已修正</span>';
        }
      } else {
        alert("修正失败: " + (await response.text()));
      }
    } catch (e) {
      alert("修正请求失败: " + e.message);
    }
  }

  async function startRun() {
    const error = document.getElementById("form-error");
    const button = document.getElementById("start-run");
    error.textContent = "";

    const file = document.getElementById("records-file").files[0];
    if (!file) {
      error.textContent = "请先选择客服回复 JSON 文件。";
      return;
    }

    if (!document.getElementById("external-ack").checked) {
      error.textContent = "请确认外部处理授权。";
      return;
    }

    let records;
    try {
      records = await loadJsonFile(file);
    } catch (e) {
      error.textContent = `文件读取失败：${e.message}`;
      return;
    }

    if (!Array.isArray(records)) {
      error.textContent = "JSON 顶层必须是数组。";
      return;
    }

    button.disabled = true;
    button.textContent = "正在提交…";

    let response;
    try {
      response = await fetch("/runs", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({
          request_id: requestId(),
          records,
          manual_review_enabled: document.getElementById("manual-review").checked,
          external_processing_acknowledged: true
        })
      });
    } catch (e) {
      error.textContent = `无法连接后端：${e.message}`;
      button.disabled = false;
      button.textContent = "创建检测运行";
      return;
    }

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      error.textContent = payload.detail || "创建运行失败，请检查后端日志和 LLM 配置";
      button.disabled = false;
      button.textContent = "创建检测运行";
      return;
    }

    runId = payload.data && payload.data.run_id ? payload.data.run_id : requestId();

    show("run-summary", `
      <h2>运行摘要</h2>
      <p><strong>运行ID:</strong> ${runId}</p>
      <p><strong>记录数:</strong> ${records.length} 条</p>
      <p><strong>多线程:</strong> 5 线程并行检测</p>
      <button class="secondary" id="refresh-run" type="button">刷新进度</button>
    `);

    show("progress", `
      <h2>检测进度</h2>
      <p>运行已创建，等待检测器处理。</p>
      <progress max="100" value="0"></progress>
    `);

    document.getElementById("export-links").innerHTML = [
      "predictions.json",
      "evaluation.json",
      "report.md",
      "feedback.json"
    ].map(a => `<a href="/runs/${runId}/downloads/${a}">${a}</a>`).join(" ");

    const truthFile = document.getElementById("ground-truth-file").files[0];
    if (truthFile) {
      try {
        groundTruth = await loadJsonFile(truthFile);
      } catch (e) {
        error.textContent = `官方标注读取失败：${e.message}`;
      }
    }

    document.getElementById("refresh-run").onclick = refreshRun;
    button.textContent = "已提交";

    if (progressTimer) clearInterval(progressTimer);
    progressTimer = setInterval(async () => {
      await refreshRun();
      const text = document.getElementById("progress").textContent;
      if (text.includes("frozen") || text.includes("retryable_partial") || text.includes("abandoned")) {
        clearInterval(progressTimer);
        progressTimer = null;
      }
    }, 3000);
  }

  async function refreshRun() {
    if (!runId) return;

    const response = await fetch(`/runs/${runId}/progress`, {
      headers: {"Accept": "application/json"}
    });
    const payload = await response.json();
    const data = payload.data || {};
    const completed = data.completed ?? data.completed_count ?? 0;
    const total = data.total ?? data.total_count ?? "—";

    show("progress", `
      <h2>检测进度</h2>
      <p>${completed} / ${total} 条记录 (${data.state || "unknown"})</p>
      <progress max="${total || 1}" value="${completed}"></progress>
    `);

    if (data.state === "frozen" || data.state === "retryable_partial") {
      // 上传 ground truth 并运行评测
      if (data.state === "frozen" && groundTruth) {
        await fetch(`/runs/${runId}/ground-truth`, {
          method: "POST",
          headers: {"Content-Type": "application/json", "Accept": "application/json"},
          body: JSON.stringify({request_id: requestId(), records: groundTruth})
        });

        const evaluation = await fetch(`/runs/${runId}/evaluation`, {
          method: "POST",
          headers: {"Content-Type": "application/json", "Accept": "application/json"},
          body: JSON.stringify({request_id: requestId()})
        });

        if (evaluation.ok) {
          const evalData = (await evaluation.json()).data;
          show("evaluation", `
            <h2>评测指标</h2>
            <div class="eval-metrics">
              <div class="metric"><strong>TP:</strong> ${evalData.tp}</div>
              <div class="metric"><strong>FP:</strong> ${evalData.fp}</div>
              <div class="metric"><strong>FN:</strong> ${evalData.fn}</div>
              <div class="metric"><strong>Precision:</strong> ${(evalData.precision.value * 100).toFixed(1)}%</div>
              <div class="metric"><strong>Recall:</strong> ${(evalData.recall.value * 100).toFixed(1)}%</div>
              <div class="metric"><strong>F1:</strong> ${(evalData.f1.value * 100).toFixed(1)}%</div>
            </div>
          `);
        }
      }

      // 获取检测结果
      const resultResponse = await fetch(`/runs/${runId}/results`, {
        headers: {"Accept": "application/json"}
      });

      if (resultResponse.ok) {
        const resultPayload = await resultResponse.json();
        currentResults = resultPayload.data?.results || [];

        // 渲染结果表格
        renderResults(currentResults);

        // 渲染图表
        document.getElementById("charts").style.display = "block";
        renderSeverityChart(currentResults);
        renderTypeChart(currentResults);

        // 如果开启了人工复审，渲染复审界面
        if (document.getElementById("manual-review").checked) {
          renderReview(currentResults);
        }
      }
    }
  }

  // 监听窗口大小变化，重新渲染图表
  window.addEventListener("resize", () => {
    if (severityChart) severityChart.resize();
    if (typeChart) typeChart.resize();
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("records-file").addEventListener("change", async e => {
      const file = e.target.files[0];
      document.getElementById("records-name").textContent = file
        ? `${file.name}（已选择，点击创建检测运行后上传）`
        : "尚未选择文件";

      if (!file) return;
      try {
        const records = await loadJsonFile(file);
        if (!Array.isArray(records)) throw new Error("JSON 顶层必须是数组");
        document.getElementById("records-name").textContent = `${file.name}（${records.length} 条记录，待上传）`;
      } catch (error) {
        document.getElementById("form-error").textContent = `文件读取失败：${error.message}`;
      }
    });

    document.getElementById("ground-truth-file").addEventListener("change", e => {
      document.getElementById("ground-truth-name").textContent = e.target.files[0]?.name || "尚未选择文件";
    });

    document.getElementById("start-run").addEventListener("click", startRun);
  });

  window.Dashboard = {
    postJson,
    loadJsonFile,
    startRun,
    refreshRun,
    showDetail,
    confirmReview,
    correctReview,
    submitCorrection
  };
})();
