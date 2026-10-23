// =========================================================
// RAHMAT JEPARA - MOBILE DRAWER NAVIGATION
// Menu horizontal tetap tampil. Tombol ☰ adalah akses tambahan.
// =========================================================

document.addEventListener("DOMContentLoaded", function () {
    const menuToggle = document.getElementById("menuToggle");
    if (!menuToggle) return;

    menuToggle.setAttribute("type", "button");
    menuToggle.setAttribute("aria-label", "Buka menu navigasi");
    menuToggle.setAttribute("aria-expanded", "false");

    // Buat drawer satu kali dari JS supaya markup semua halaman tetap konsisten.
    const overlay = document.createElement("div");
    overlay.className = "mobile-nav-overlay";
    overlay.setAttribute("aria-hidden", "true");

    const drawer = document.createElement("aside");
    drawer.className = "mobile-nav-drawer";
    drawer.setAttribute("aria-hidden", "true");
    drawer.innerHTML = `
        <div class="mobile-drawer-head">
            <a href="index.html" class="mobile-drawer-brand" aria-label="Rahmat Jepara - Home">
                <span class="mobile-drawer-logo">
                    <img src="images/logo-rahmat-jepara.png" alt="Rahmat Jepara Furniture">
                </span>
                <span class="mobile-drawer-brand-title">FURNITURE JATI</span>
            </a>
            <button type="button" class="mobile-drawer-close" aria-label="Tutup menu">×</button>
        </div>
        <nav class="mobile-drawer-links" aria-label="Menu mobile">
            <a href="index.html">Home</a>
            <a href="produk.html">Produk</a>
            <a href="customer-service.html">Customer Service</a>
            <a href="kontak.html">Kontak</a>
        </nav>
        <div class="mobile-drawer-foot">
            <span>RAHMAT JEPARA</span>
            <small>Furniture Kayu Jati • Jepara</small>
        </div>
    `;

    document.body.appendChild(overlay);
    document.body.appendChild(drawer);

    const closeButton = drawer.querySelector(".mobile-drawer-close");
    const drawerLinks = drawer.querySelectorAll(".mobile-drawer-links a");

    // Tandai link aktif sesuai halaman saat ini.
    const current = (window.location.pathname.split("/").pop() || "index.html").toLowerCase();
    drawerLinks.forEach((link) => {
        const target = (link.getAttribute("href") || "").toLowerCase();
        if (target === current) link.classList.add("active");
    });

    function openDrawer() {
        drawer.classList.add("open");
        overlay.classList.add("open");
        drawer.setAttribute("aria-hidden", "false");
        overlay.setAttribute("aria-hidden", "false");
        menuToggle.setAttribute("aria-expanded", "true");
        document.body.classList.add("mobile-nav-open");
    }

    function closeDrawer() {
        drawer.classList.remove("open");
        overlay.classList.remove("open");
        drawer.setAttribute("aria-hidden", "true");
        overlay.setAttribute("aria-hidden", "true");
        menuToggle.setAttribute("aria-expanded", "false");
        document.body.classList.remove("mobile-nav-open");
    }

    // Pakai stopImmediatePropagation supaya listener navbar lama tidak ikut mengubah menu horizontal.
    menuToggle.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (drawer.classList.contains("open")) closeDrawer();
        else openDrawer();
    }, true);

    closeButton.addEventListener("click", closeDrawer);
    overlay.addEventListener("click", closeDrawer);
    drawerLinks.forEach((link) => link.addEventListener("click", closeDrawer));

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && drawer.classList.contains("open")) closeDrawer();
    });
});
