document.addEventListener("DOMContentLoaded", () => {
  const searchForm = document.getElementById("search-form");
  const searchInput = document.getElementById("search-input");
  const loader = document.getElementById("loader");
  const resultsSection = document.getElementById("results-section");
  const winnerBanner = document.getElementById("winner-banner");
  const voiceText = document.getElementById("voice-text");
  const btnSpeak = document.getElementById("btn-speak");
  const rohlikContent = document.getElementById("rohlik-content");
  const kosikContent = document.getElementById("kosik-content");
  const stapleChips = document.querySelectorAll(".chip");
  const btnToggleIfttt = document.getElementById("btn-toggle-ifttt");
  const iftttModal = document.getElementById("ifttt-modal");
  const btnCloseModal = document.getElementById("btn-close-modal");

  let currentVoiceText = "";

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
    } catch (err) {
      alert(`Error comparing prices: ${err.message}`);
    } finally {
      loader.classList.add("hidden");
    }
  }

  // Render results
  function renderResults(data) {
    resultsSection.classList.remove("hidden");

    // Voice card
    currentVoiceText = data.voice_summary_en || "No voice summary available.";
    voiceText.textContent = currentVoiceText;

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
      winnerBanner.innerHTML = `🏆 <strong>Rohlík is cheaper!</strong> Save ${data.price_difference} CZK per ${unitLabel} (${data.percentage_savings}%).`;
    } else if (data.advantage === "kosik_cheaper" && data.price_difference && parseFloat(data.price_difference) > 0) {
      winnerBanner.classList.remove("hidden");
      winnerBanner.classList.add("kosik");
      winnerBanner.innerHTML = `🏆 <strong>Košík is cheaper!</strong> Save ${data.price_difference} CZK per ${unitLabel} (${data.percentage_savings}%).`;
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
      ? `<span class="best-value-pill">🏅 Best Value / ${bestUnit}</span>`
      : "";
    const unitPriceText = product.unit_price
      ? `<span class="unit-price">${Number(product.unit_price).toFixed(2)} CZK / ${product.unit_type}</span>`
      : "";
    const origPriceText = hasSale
      ? `<span class="price-original">${Number(product.original_price).toFixed(2)} CZK</span>`
      : "";
    const imgHtml = product.image_url
      ? `<img src="${product.image_url}" alt="${product.name}" class="product-img" onerror="this.style.display='none'"/>`
      : `<span style="font-size: 2.5rem;">📦</span>`;
    const brandText = product.brand
      ? `<span class="product-brand">${product.brand}</span>`
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
            <span class="unit-pill">${product.package_amount || ''} ${product.unit_type}</span>
          </div>
          ${brandText}
          <h3 class="product-title-sm">${product.name}</h3>
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

  // Read aloud simulation with Web Speech API
  btnSpeak.addEventListener("click", () => {
    if (!currentVoiceText || !('speechSynthesis' in window)) {
      alert("Text-to-speech is not supported in this browser.");
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(currentVoiceText);
    utterance.lang = "en-US";
    utterance.rate = 1.0;
    window.speechSynthesis.speak(utterance);
  });

  // Modal toggle
  btnToggleIfttt.addEventListener("click", () => {
    iftttModal.classList.remove("hidden");
  });
  btnCloseModal.addEventListener("click", () => {
    iftttModal.classList.add("hidden");
  });
  iftttModal.addEventListener("click", (e) => {
    if (e.target === iftttModal) {
      iftttModal.classList.add("hidden");
    }
  });
});
