(() => {
  const snapshotEndpoint = "/api/method/imogi_finance.api.reporting.get_dashboard_snapshot";

  const renderChartJs = (canvas, labels, inflow, outflow) => {
    if (!window.Chart || !canvas) return;
    return new window.Chart(canvas, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Inflow",
            data: inflow,
            backgroundColor: "#2563EB",
          },
          {
            label: "Outflow",
            data: outflow,
            backgroundColor: "#DC2626",
          },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { position: "bottom" },
          title: { display: true, text: "Branch Daily Report" },
        },
      },
    });
  };

  const renderPlotly = (el, labels, inflow, outflow) => {
    if (!window.Plotly || !el) return;
    return window.Plotly.newPlot(
      el,
      [
        { x: labels, y: inflow, name: "Inflow", type: "bar", marker: { color: "#2563EB" } },
        { x: labels, y: outflow, name: "Outflow", type: "bar", marker: { color: "#DC2626" } },
      ],
      { barmode: "group", title: "Branch Daily Report", margin: { t: 40 } },
      { displaylogo: false }
    );
  };

  const renderSnapshot = (snapshot) => {
    const labels = [];
    const inflow = [];
    const outflow = [];

    (snapshot.branches || []).forEach((branch) => {
      labels.push(branch.branch);
      inflow.push(branch.inflow || 0);
      outflow.push(branch.outflow || 0);
    });

    const chartCanvas = document.querySelector("[data-report-dashboard-chart]");
    const plotlyContainer = document.querySelector("[data-report-dashboard-plotly]");

    if (chartCanvas) {
      renderChartJs(chartCanvas, labels, inflow, outflow);
    } else if (plotlyContainer) {
      renderPlotly(plotlyContainer, labels, inflow, outflow);
    }

    const consolidated = snapshot.consolidated || {};
    const summary = document.querySelector("[data-report-dashboard-summary]");
    if (summary) {
      summary.innerHTML = `
        <div><strong>Opening:</strong> ${consolidated.opening_balance || 0}</div>
        <div><strong>Inflow:</strong> ${consolidated.inflow || 0}</div>
        <div><strong>Outflow:</strong> ${consolidated.outflow || 0}</div>
        <div><strong>Closing:</strong> ${consolidated.closing_balance || 0}</div>
      `;
    }
  };

  const loadSnapshot = async () => {
    try {
      const response = await fetch(snapshotEndpoint, { method: "POST" });
      const payload = await response.json();
      const snapshot = payload.message || payload;
      renderSnapshot(snapshot);
    } catch (error) {
      // Soft-fail on dashboards; administrators can inspect console
      console.warn("[IMOGI Finance] Unable to load reporting dashboard", error);
    }
  };

  if (document.readyState === "complete" || document.readyState === "interactive") {
    loadSnapshot();
  } else {
    document.addEventListener("DOMContentLoaded", loadSnapshot);
  }
})();
