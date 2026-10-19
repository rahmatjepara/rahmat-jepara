(() => {
    "use strict";

    const reduceMotion =
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /*
       Delay dibuat lebih rapat daripada versi sebelumnya,
       supaya item terasa mengalir, bukan muncul satu-satu terlalu keras.
    */
    const groups = [
        {
            selector: ".hero, .hero-section, .products-header, .section-heading, .room-heading",
            baseDelay: 0,
            step: 0
        },
        {
            selector: ".trust-bar > *, .trust-item",
            baseDelay: 20,
            step: 45
        },
        {
            selector: ".room-card",
            baseDelay: 15,
            step: 55
        },
        {
            selector: ".product-card",
            baseDelay: 10,
            step: 50
        },
        {
            selector: ".why-us > *, .why-grid > *, .feature-card, .service-card",
            baseDelay: 10,
            step: 45
        },
        {
            selector: ".cta, .cta-section, .home-logo-section, .footer",
            baseDelay: 0,
            step: 0
        }
    ];

    const revealElements = [];
    const seen = new Set();

    groups.forEach((group) => {
        const items = Array.from(
            document.querySelectorAll(group.selector)
        );

        items.forEach((element, index) => {
            if (seen.has(element)) return;
            seen.add(element);

            element.classList.add("reveal-item");

            /*
               Delay tidak dibiarkan terus membesar.
               Maksimal 6 langkah supaya section panjang tetap natural.
            */
            const localIndex = index % 6;

            element.style.setProperty(
                "--reveal-delay",
                `${group.baseDelay + localIndex * group.step}ms`
            );

            revealElements.push(element);
        });
    });

    if (reduceMotion) {
        revealElements.forEach((element) => {
            element.classList.add("is-visible");
        });
        return;
    }

    /*
       Trigger lebih awal:
       elemen mulai animasi sebelum benar-benar masuk penuh ke viewport.
       Ini menghilangkan rasa "kaget".
    */
    const observer = new IntersectionObserver(
        (entries, obs) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;

                entry.target.classList.add("is-visible");
                obs.unobserve(entry.target);
            });
        },
        {
            root: null,
            threshold: 0.025,
            rootMargin: "0px 0px 12% 0px"
        }
    );

    revealElements.forEach((element) => {
        observer.observe(element);
    });

    /*
       Bagian yang sudah terlihat saat halaman pertama dibuka
       dibuat muncul halus tanpa menunggu observer terlambat.
    */
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            revealElements.forEach((element) => {
                const rect = element.getBoundingClientRect();

                if (
                    rect.top < window.innerHeight * 0.96 &&
                    rect.bottom > 0
                ) {
                    element.classList.add("is-visible");
                    observer.unobserve(element);
                }
            });
        });
    });
})();