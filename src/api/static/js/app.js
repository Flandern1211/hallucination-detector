(function () {
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

  window.Dashboard = {postJson, loadJsonFile, renderChart};
})();
