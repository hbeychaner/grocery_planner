document.addEventListener("DOMContentLoaded", () => {
  const searchForm = document.getElementById("search-form");
  const searchInput = document.getElementById("search-input");
  const loader = document.getElementById("loader");
  const resultsSection = document.getElementById("results-section");
  const winnerBanner = document.getElementById("winner-banner");
  const rohlikContent = document.getElementById("rohlik-content");
  const kosikContent = document.getElementById("kosik-content");
  const kupiContent = document.getElementById("kupi-content");
  const stapleChips = document.querySelectorAll(".chip");

  function escapeHtml(val) {
    return String(val ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function safeUrl(url) {
    const s = String(url ?? "").trim();
    return (s.startsWith("https://") || s.startsWith("http://")) ? escapeHtml(s) : "#";
  }

  // Perform price comparison
  async function performSearch(query) {
    if (!query || !query.trim()) return;

    loader.classList.remove("hidden");
    resultsSection.classList.add("hidden");

    try {
      const response = await fetch(`/api/v1/compare?q=${encodeURIComponent(query)}&lang=en`);
      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`);
      }

      const data = await response.json();
      renderResults(data);

      // Fetch Kupi.cz supermarket deals in parallel without blocking main UI
      fetch(`/api/v1/compare/kupi?q=${encodeURIComponent(query)}`)
        .then(r => r.ok ? r.json() : [])
        .then(renderKupiDeals)
        .catch(() => renderKupiDeals([]));
    } catch (err) {
      alert(`Error comparing prices: ${err.message}`);
    } finally {
      loader.classList.add("hidden");
    }
  }

  // Render results
  function renderResults(data) {
    resultsSection.classList.remove("hidden");

    // Winner banner (only display when there is a distinct price advantage)
    winnerBanner.className = "winner-banner";
    const rawUnit = (data.primary_pair && data.primary_pair.rohlik_product && data.primary_pair.rohlik_product.unit_type)
      || (data.primary_pair && data.primary_pair.kosik_product && data.primary_pair.kosik_product.unit_type)
      || (data.rohlik_ranked && data.rohlik_ranked[0] && data.rohlik_ranked[0].unit_type)
      || (data.kosik_ranked && data.kosik_ranked[0] && data.kosik_ranked[0].unit_type)
      || "unit";
    const unitLabel = rawUnit === "pcs" ? "piece" : rawUnit;

    if (data.advantage === "rohlik_cheaper" && data.price_difference && parseFloat(data.price_difference) > 0) {
      winnerBanner.classList.remove("hidden");
      winnerBanner.classList.add("rohlik");
      winnerBanner.innerHTML = `<strong>Rohlík is cheaper.</strong> Save ${escapeHtml(data.price_difference)} CZK per ${escapeHtml(unitLabel)} (${escapeHtml(data.percentage_savings)}%).`;
    } else if (data.advantage === "kosik_cheaper" && data.price_difference && parseFloat(data.price_difference) > 0) {
      winnerBanner.classList.remove("hidden");
      winnerBanner.classList.add("kosik");
      winnerBanner.innerHTML = `<strong>Košík is cheaper.</strong> Save ${escapeHtml(data.price_difference)} CZK per ${escapeHtml(unitLabel)} (${escapeHtml(data.percentage_savings)}%).`;
    } else {
      // Hide banner on ties or when neither store has a clear advantage
      winnerBanner.classList.add("hidden");
      winnerBanner.innerHTML = "";
    }

    // Use ranked lists for display (fall back to candidates if ranked is empty)
    const rohlikList = (data.rohlik_ranked && data.rohlik_ranked.length)
      ? data.rohlik_ranked
      : (data.rohlik_candidates || []);
    const kosikList = (data.kosik_ranked && data.kosik_ranked.length)
      ? data.kosik_ranked
      : (data.kosik_candidates || []);

    // Identify the best-value product IDs (index 0 in each ranked list)
    const rohlikBestId = rohlikList.length ? rohlikList[0].product_id : null;
    const kosikBestId = kosikList.length ? kosikList[0].product_id : null;

    renderRankedList(rohlikContent, rohlikList, "Rohlík", rohlikBestId);
    renderRankedList(kosikContent, kosikList, "Košík", kosikBestId);
  }

  function renderKupiDeals(deals) {
    if (!kupiContent) return;
    if (!deals || deals.length === 0) {
      kupiContent.innerHTML = `<p style="color: #94a3b8; font-size: 0.9rem;">No active Kupi.cz leaflet promotions found for this item.</p>`;
      return;
    }
    kupiContent.innerHTML = deals.map(d => {
      const unitTxt = d.unit_price ? `${Number(d.unit_price).toFixed(2)} CZK / ${d.unit_type}` : "";
      return `
        <div style="border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px; background: #f8fafc;">
          <div style="font-size: 0.78rem; font-weight: 700; color: #0f172a; text-transform: uppercase;">${escapeHtml(d.store)}</div>
          <div style="font-weight: 600; margin: 4px 0; font-size: 0.92rem;">${escapeHtml(d.product_name)}</div>
          <div style="display: flex; justify-content: space-between; align-items: baseline;">
            <span style="font-weight: 700; color: #16a34a;">${Number(d.price).toFixed(2)} CZK</span>
            <span style="font-size: 0.8rem; color: #64748b;">${escapeHtml(unitTxt)}</span>
          </div>
          <a href="${safeUrl(d.url)}" target="_blank" rel="noopener noreferrer" class="product-link" style="display:inline-block; margin-top:6px; font-size:0.8rem;">View deal &rarr;</a>
        </div>
      `;
    }).join("");
  }

  function renderRankedList(container, products, storeName, bestId) {
    if (!products || products.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 40px 10px; color: #94a3b8;">
          <p>No matching products found on ${storeName}.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = products.map((product, index) => {
      const isBest = product.product_id === bestId;
      return renderProductCard(product, storeName, isBest, index + 1);
    }).join("");
  }

  function renderProductCard(product, storeName, isBest, rank) {
    const hasSale = product.is_on_sale && product.original_price;
    const salePill = hasSale ? `<span class="sale-pill">SALE</span>` : "";
    const bestUnit = product.unit_type === "pcs" ? "piece" : (product.unit_type || "unit");
    const bestPill = isBest
      ? `<span class="best-value-pill">Best Value / ${escapeHtml(bestUnit)}</span>`
      : "";
    const unitPriceText = product.unit_price
      ? `<span class="unit-price">${Number(product.unit_price).toFixed(2)} CZK / ${escapeHtml(product.unit_type)}</span>`
      : "";
    const origPriceText = hasSale
      ? `<span class="price-original">${Number(product.original_price).toFixed(2)} CZK</span>`
      : "";
    const imgHtml = product.image_url
      ? `<img src="${safeUrl(product.image_url)}" alt="${escapeHtml(product.name)}" class="product-img" onerror="this.style.display='none'"/>`
      : `<span style="font-size: 0.75rem; color: #94a3b8;">No image</span>`;
    const brandText = product.brand
      ? `<span class="product-brand">${escapeHtml(product.brand)}</span>`
      : "";

    return `
      <div class="product-card-row ${isBest ? "best-value" : ""}">
        <div class="rank-badge">#${rank}</div>
        <div class="product-img-wrapper-sm">
          ${imgHtml}
        </div>
        <div class="product-info">
          <div class="product-meta">
            ${bestPill}${salePill}
            <span class="unit-pill">${escapeHtml(product.package_amount || '')} ${escapeHtml(product.unit_type)}</span>
          </div>
          ${brandText}
          <h3 class="product-title-sm">${escapeHtml(product.name)}</h3>
          <div class="price-row">
            <div>
              ${origPriceText}
              <span class="price-main">${Number(product.price).toFixed(2)} <span style="font-size: 0.85rem; font-weight:600;">CZK</span></span>
            </div>
            ${unitPriceText}
          </div>
          ${product.url ? `<a href="${product.url}" target="_blank" class="product-link">View on ${storeName} &rarr;</a>` : ''}
        </div>
      </div>
    `;
  }

  // Form submission
  searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    performSearch(searchInput.value);
  });

  // Staples chip click
  stapleChips.forEach(chip => {
    chip.addEventListener("click", () => {
      const query = chip.getAttribute("data-query");
      searchInput.value = query;
      performSearch(query);
    });
  });
});
