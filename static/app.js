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

    // Winner banner
    winnerBanner.className = "winner-banner";
    if (data.advantage === "rohlik_cheaper") {
      winnerBanner.classList.add("rohlik");
      winnerBanner.innerHTML = `🏆 <strong>Rohlík is cheaper!</strong> Save ${data.price_difference} CZK (${data.percentage_savings}%) on this item.`;
    } else if (data.advantage === "kosik_cheaper") {
      winnerBanner.classList.add("kosik");
      winnerBanner.innerHTML = `🏆 <strong>Košík is cheaper!</strong> Save ${data.price_difference} CZK (${data.percentage_savings}%) on this item.`;
    } else if (data.advantage === "tied") {
      winnerBanner.classList.add("tied");
      winnerBanner.innerHTML = `⚖️ <strong>It's a tie!</strong> Both supermarkets offer the same price.`;
    } else {
      winnerBanner.classList.add("tied");
      winnerBanner.innerHTML = `ℹ️ Item found in only one store.`;
    }

    // Render Store Cards
    const pair = data.primary_pair || {};
    renderProductCard(rohlikContent, pair.rohlik_product, "Rohlík");
    renderProductCard(kosikContent, pair.kosik_product, "Košík");
  }

  function renderProductCard(container, product, storeName) {
    if (!product) {
      container.innerHTML = `
        <div style="text-align: center; padding: 40px 10px; color: #94a3b8;">
          <p>No matching product found on ${storeName}.</p>
        </div>
      `;
      return;
    }

    const hasSale = product.is_on_sale && product.original_price;
    const salePill = hasSale ? `<span class="sale-pill">SALE</span>` : "";
    const unitPriceText = product.unit_price ? `(${product.unit_price} CZK / ${product.unit_type})` : "";
    const origPriceText = hasSale ? `<span class="price-original">${product.original_price} CZK</span>` : "";
    const imgHtml = product.image_url
      ? `<img src="${product.image_url}" alt="${product.name}" class="product-img" onerror="this.style.display='none'"/>`
      : `<span style="font-size: 3rem;">📦</span>`;

    container.innerHTML = `
      <div class="product-img-wrapper">
        ${imgHtml}
      </div>
      <h3 class="product-title">${product.name}</h3>
      <div class="product-meta">
        ${salePill}
        <span class="unit-pill">${product.package_amount || ''} ${product.unit_type}</span>
      </div>
      <div class="price-box">
        <div>
          ${origPriceText}
          <div class="price-main">${product.price} <span style="font-size: 0.95rem; font-weight: 600;">CZK</span></div>
        </div>
        <div class="unit-price">${unitPriceText}</div>
      </div>
      ${product.url ? `<a href="${product.url}" target="_blank" class="product-link">View on ${storeName} &rarr;</a>` : ''}
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
