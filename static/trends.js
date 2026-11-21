document.addEventListener("DOMContentLoaded", () => {
  const statItems = document.getElementById("stat-items");
  const statSnapshots = document.getElementById("stat-snapshots");
  const statLastRun = document.getElementById("stat-last-run");
  const watchlistContainer = document.getElementById("watchlist-container");
  const filterInput = document.getElementById("filter-items");
  const addItemForm = document.getElementById("add-item-form");
  const newItemInput = document.getElementById("new-item-input");
  const btnRunCheck = document.getElementById("btn-run-check");
  const runStatus = document.getElementById("run-status");
  const chartTitle = document.getElementById("chart-title");
  const chartSubtitle = document.getElementById("chart-subtitle");
  const daysSelect = document.getElementById("days-select");
  const snapshotsTbody = document.getElementById("snapshots-tbody");
  const chartCanvas = document.getElementById("price-chart");

  let allItems = [];
  let selectedQuery = null;
  let priceChart = null;

  async function loadWatchlist() {
    const resp = await fetch("/api/v1/history/items");
    const data = await resp.json();
    statItems.textContent = data.stats.tracked_items_count;
    statSnapshots.textContent = data.stats.total_snapshots;
    statLastRun.textContent = data.stats.last_recorded_at || "Never";
    allItems = data.items || [];

    if (!selectedQuery && allItems.length > 0) {
      const withData = allItems.find(i => i.latest_rohlik_unit_price !== null || i.latest_kosik_unit_price !== null);
      selectedQuery = (withData || allItems[0]).query;
    }

    renderWatchlist();
    if (selectedQuery) {
      await loadItemSeries(selectedQuery);
    }
  }

  function renderWatchlist() {
    const filter = (filterInput.value || "").trim().toLowerCase();
    const filtered = allItems.filter(item =>
      item.query.toLowerCase().includes(filter) ||
      (item.query_cs && item.query_cs.toLowerCase().includes(filter))
    );

    watchlistContainer.innerHTML = filtered.map(item => {
      const isSelected = item.query === selectedQuery;
      const rPrice = item.latest_rohlik_unit_price !== null ? `${item.latest_rohlik_unit_price.toFixed(1)}` : "—";
      const kPrice = item.latest_kosik_unit_price !== null ? `${item.latest_kosik_unit_price.toFixed(1)}` : "—";
      const unit = item.latest_unit_type || "";
      return `
        <button
          class="chip"
          data-query="${item.query}"
          style="display: flex; justify-content: space-between; align-items: center; text-align: left; width: 100%; border-radius: 8px; padding: 8px 10px; ${isSelected ? 'background:#e0e7ff; border-color:#6366f1; font-weight:600;' : ''}"
        >
          <span>${item.query}</span>
          <span style="font-size: 0.78rem; color: #475569;">R:${rPrice} / K:${kPrice} ${unit}</span>
        </button>
      `;
    }).join("");

    watchlistContainer.querySelectorAll("button[data-query]").forEach(btn => {
      btn.addEventListener("click", async () => {
        selectedQuery = btn.getAttribute("data-query");
        renderWatchlist();
        await loadItemSeries(selectedQuery);
      });
    });
  }

  async function loadItemSeries(query) {
    const days = daysSelect.value || "90";
    const resp = await fetch(`/api/v1/history/series?q=${encodeURIComponent(query)}&days=${days}`);
    const data = await resp.json();

    const unitLabel = data.unit_type === "pcs" ? "piece" : (data.unit_type || "unit");
    chartTitle.textContent = `${data.query}`;
    chartSubtitle.textContent = `Lowest available unit price (CZK per ${unitLabel}) over the last ${days} days`;

    renderChart(data, unitLabel);
    renderTable(data, unitLabel);
  }

  function renderChart(data, unitLabel) {
    const timestamps = Array.from(new Set([
      ...data.rohlik_series.map(p => p.recorded_at),
      ...data.kosik_series.map(p => p.recorded_at),
    ])).sort();

    const rMap = new Map(data.rohlik_series.map(p => [p.recorded_at, p.unit_price]));
    const kMap = new Map(data.kosik_series.map(p => [p.recorded_at, p.unit_price]));

    if (priceChart) {
      priceChart.destroy();
    }

    priceChart = new Chart(chartCanvas, {
      type: "line",
      data: {
        labels: timestamps,
        datasets: [
          {
            label: `Rohlík.cz (CZK/${unitLabel})`,
            data: timestamps.map(t => rMap.has(t) ? rMap.get(t) : null),
            borderColor: "#7c3aed",
            backgroundColor: "rgba(124, 58, 237, 0.12)",
            tension: 0.25,
            spanGaps: true,
          },
          {
            label: `Košík.cz (CZK/${unitLabel})`,
            data: timestamps.map(t => kMap.has(t) ? kMap.get(t) : null),
            borderColor: "#d97706",
            backgroundColor: "rgba(217, 119, 6, 0.12)",
            tension: 0.25,
            spanGaps: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: {
            beginAtZero: false,
            title: { display: true, text: `CZK per ${unitLabel}` },
          },
        },
      },
    });
  }

  function renderTable(data, unitLabel) {
    const combined = [
      ...data.rohlik_series.map(p => ({ ...p, storeLabel: "Rohlík" })),
      ...data.kosik_series.map(p => ({ ...p, storeLabel: "Košík" })),
    ].sort((a, b) => b.recorded_at.localeCompare(a.recorded_at));

    if (combined.length === 0) {
      snapshotsTbody.innerHTML = `<tr><td colspan="5" style="padding: 16px; text-align: center; color: #94a3b8;">No price snapshots recorded for "${data.query}" yet. Click "Run Check" to record data now.</td></tr>`;
      return;
    }

    snapshotsTbody.innerHTML = combined.map(p => {
      const rowUnit = p.unit_type === "pcs" ? "piece" : (p.unit_type || unitLabel);
      return `
      <tr style="border-bottom: 1px solid #f1f5f9;">
        <td style="padding: 8px;">${p.recorded_at}</td>
        <td style="padding: 8px; font-weight: 600;">${p.storeLabel}</td>
        <td style="padding: 8px;">${p.product_name} ${p.is_on_sale ? '<span class="sale-pill">SALE</span>' : ''}</td>
        <td style="padding: 8px;">${p.price.toFixed(2)} CZK</td>
        <td style="padding: 8px; font-weight: 600;">${p.unit_price !== null ? `${p.unit_price.toFixed(2)} CZK/${rowUnit}` : '—'}</td>
      </tr>
    `;
    }).join("");
  }

  filterInput.addEventListener("input", renderWatchlist);
  daysSelect.addEventListener("change", () => {
    if (selectedQuery) loadItemSeries(selectedQuery);
  });

  addItemForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = newItemInput.value.trim();
    if (!q) return;
    await fetch("/api/v1/history/items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q }),
    });
    newItemInput.value = "";
    selectedQuery = q.toLowerCase();
    await loadWatchlist();
  });

  btnRunCheck.addEventListener("click", async () => {
    btnRunCheck.disabled = true;
    btnRunCheck.textContent = "⏳ Checking...";
    runStatus.classList.remove("hidden");
    runStatus.textContent = "Running price check across sample of 10 tracked groceries...";
    const pollTimer = setInterval(loadWatchlist, 3000);
    try {
      const resp = await fetch("/api/v1/history/run?limit=10", { method: "POST" });
      const res = await resp.json();
      runStatus.textContent = `Checked ${res.succeeded}/${res.total_items} items (${res.snapshots_recorded} snapshots recorded in ${res.duration_seconds}s).`;
      await loadWatchlist();
    } catch (err) {
      runStatus.textContent = `Price check failed: ${err.message}`;
    } finally {
      clearInterval(pollTimer);
      btnRunCheck.disabled = false;
      btnRunCheck.textContent = "▶ Run Check (Sample 10)";
    }
  });

  loadWatchlist();
});
