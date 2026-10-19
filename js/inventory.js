(() => {
    "use strict";

    const STATUS_FILE = "products-status.json";

    function setBadge(card, product) {
        const badge = card.querySelector(".product-status");
        if (!badge || !product) return;

        const stock = Number(product.stock || 0);
        const status = stock > 0 ? "AVAILABLE" : "SOLD OUT";

        badge.textContent = status;
        badge.classList.toggle("available", status === "AVAILABLE");
        badge.classList.toggle("sold-out", status === "SOLD OUT");

        card.dataset.stock = String(stock);
        card.dataset.status = status.toLowerCase();
    }

    async function loadInventoryStatus() {
        try {
            const response = await fetch(
                STATUS_FILE + "?v=" + Date.now(),
                { cache: "no-store" }
            );

            if (!response.ok) throw new Error("HTTP " + response.status);

            const data = await response.json();
            const products = data.products || {};

            document.querySelectorAll(".product-card[data-code]").forEach((card) => {
                const code = card.dataset.code;
                if (products[code]) setBadge(card, products[code]);
            });

            if (typeof applyProductFilters === "function") {
                applyProductFilters();
            }
        } catch (error) {
            console.warn("Status stok gagal dimuat. Badge HTML bawaan tetap dipakai.", error);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", loadInventoryStatus);
    } else {
        loadInventoryStatus();
    }

    window.reloadRahmatJeparaInventory = loadInventoryStatus;
})();
