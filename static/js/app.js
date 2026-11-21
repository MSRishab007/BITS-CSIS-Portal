/* Site-wide interactions. Loaded on every page (before Alpine).
 *
 *   - Tri-colour progress bar when leaving a page or submitting a form
 *   - Apple-Pay style tilt on .tilt cards (pointer devices only)
 *   - Count-up for [data-count] numbers
 *   - Sliding indicator for the sidebar and segmented controls
 *   - Alpine components: sidebar (collapse), cmdk (Ctrl+K command menu), donut
 *
 * Everything respects "reduce motion".
 */
(function () {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  // ---------------------------------------------------------------- progress
  function startProgress() {
    const bar = document.querySelector(".nav-progress");
    if (!bar) return;
    bar.classList.remove("done");
    void bar.offsetWidth;
    bar.classList.add("run");
  }
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
    const href = a.getAttribute("href");
    if (!href || href.startsWith("#") || a.target === "_blank" || a.hasAttribute("download")) return;
    if (href.includes("export.xlsx") || href.includes("template.") || href.includes("/bill/")) return;
    if (a.origin === location.origin) startProgress();
  });
  document.addEventListener("submit", (e) => { if (!e.defaultPrevented) startProgress(); });
  window.addEventListener("pageshow", () => {
    const bar = document.querySelector(".nav-progress");
    if (bar) { bar.classList.remove("run"); bar.classList.add("done"); }
  });

  // ---------------------------------------------------------------- tilt
  function bindTilt(el) {
    if (reduceMotion || !finePointer || el.dataset.tiltBound) return;
    el.dataset.tiltBound = "1";
    const max = parseFloat(el.dataset.tilt || "7");
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      // The edge under the cursor is pushed away from you, like pressing a card.
      el.style.setProperty("--ry", `${(x - 0.5) * -max * 2}deg`);
      el.style.setProperty("--rx", `${(y - 0.5) * max * 2}deg`);
      el.style.setProperty("--gx", `${x * 100}%`);
      el.style.setProperty("--gy", `${y * 100}%`);
      el.classList.add("is-tilting");
    });
    el.addEventListener("pointerleave", () => {
      el.classList.remove("is-tilting");
      el.style.setProperty("--rx", "0deg");
      el.style.setProperty("--ry", "0deg");
    });
  }

  // ---------------------------------------------------------------- count-up
  function countUp(el) {
    if (el.dataset.counted) return;
    el.dataset.counted = "1";
    const target = parseFloat(el.dataset.count);
    const decimals = parseInt(el.dataset.decimals || "0", 10);
    const prefix = el.dataset.prefix || "";
    const fmt = (v) => prefix + v.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    if (reduceMotion || !isFinite(target)) { el.textContent = fmt(target || 0); return; }
    const start = performance.now(), dur = 700;
    const tick = (now) => {
      const t = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = fmt(target * eased);
      if (t < 1) requestAnimationFrame(tick);
      else el.textContent = fmt(target);
    };
    requestAnimationFrame(tick);
  }

  // ---------------------------------------------------------------- sliding thumbs
  function placeThumb(container, thumb, active, vertical) {
    if (!active) { thumb.style.opacity = 0; return; }
    const c = container.getBoundingClientRect(), a = active.getBoundingClientRect();
    thumb.style.opacity = 1;
    if (vertical) {
      thumb.style.transform = `translateY(${a.top - c.top}px)`;
      thumb.style.height = `${a.height}px`;
    } else {
      thumb.style.transform = `translateX(${a.left - c.left}px)`;
      thumb.style.width = `${a.width}px`;
    }
  }
  function bindSegmented(seg) {
    const thumb = seg.querySelector(".thumb");
    if (!thumb) return;
    const place = (el) => placeThumb(seg, thumb, el, false);
    place(seg.querySelector(".on"));
    seg.querySelectorAll("a, button").forEach((el) => {
      el.addEventListener("click", () => { seg.querySelectorAll(".on").forEach((o) => o.classList.remove("on")); el.classList.add("on"); place(el); });
    });
  }
  function bindNav(nav) {
    const ind = nav.querySelector(".nav-indicator");
    if (!ind) return;
    const active = nav.querySelector(".nav-link.active");
    placeThumb(nav, ind, active, true);
    nav.querySelectorAll(".nav-link").forEach((link) => {
      link.addEventListener("click", () => placeThumb(nav, ind, link, true));
    });
  }

  function init(root = document) {
    root.querySelectorAll(".tilt").forEach(bindTilt);
    root.querySelectorAll(".segmented").forEach(bindSegmented);
    root.querySelectorAll(".nav").forEach(bindNav);
    const counters = root.querySelectorAll("[data-count]");
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver((entries) => entries.forEach((en) => {
        if (en.isIntersecting) { countUp(en.target); io.unobserve(en.target); }
      }), { threshold: 0.3 });
      counters.forEach((c) => io.observe(c));
    } else counters.forEach(countUp);
  }
  document.addEventListener("DOMContentLoaded", () => init());
  window.addEventListener("resize", () => document.querySelectorAll(".nav").forEach(bindNav));

  // ---------------------------------------------------------------- Alpine components
  document.addEventListener("alpine:init", () => {
    // Sidebar: open on mobile, collapse on desktop (remembered per browser).
    Alpine.data("shell", () => ({
      nav: false,
      collapsed: false,
      init() {
        try { this.collapsed = localStorage.getItem("sidebar-collapsed") === "1"; } catch (e) { /* storage off */ }
        this.$watch("collapsed", (v) => {
          try { localStorage.setItem("sidebar-collapsed", v ? "1" : "0"); } catch (e) { /* storage off */ }
          setTimeout(() => document.querySelectorAll(".nav").forEach(bindNav), 260);
        });
      },
    }));

    // Ctrl+K / ⌘K command menu: pages + live search of invoices, vendors, people.
    Alpine.data("cmdk", () => ({
      open: false, q: "", results: [], active: 0, loading: false, url: "", pages: [], timer: null,
      init() {
        this.url = this.$el.dataset.url;
        this.pages = JSON.parse(document.getElementById("cmdk-pages").textContent);
        this.results = this.pageMatches("");
        window.addEventListener("keydown", (e) => {
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); this.toggle(); }
          else if (e.key === "/" && !this.open && !/input|textarea|select/i.test(document.activeElement.tagName)) {
            e.preventDefault(); this.toggle();
          }
        });
        window.addEventListener("open-cmdk", () => this.toggle(true));
      },
      toggle(force) {
        this.open = force ?? !this.open;
        if (this.open) { this.q = ""; this.results = this.pageMatches(""); this.active = 0;
          this.$nextTick(() => this.$refs.input.focus()); }
      },
      pageMatches(q) {
        q = q.toLowerCase();
        return this.pages.filter((p) => !q || p.label.toLowerCase().includes(q) || (p.keywords || "").includes(q))
          .map((p) => ({ ...p, group: "Go to" }));
      },
      search() {
        clearTimeout(this.timer);
        const q = this.q.trim();
        const pages = this.pageMatches(q);
        this.results = pages;
        this.active = 0;
        if (q.length < 2) return;
        this.loading = true;
        this.timer = setTimeout(async () => {
          try {
            const res = await fetch(`${this.url}?q=${encodeURIComponent(q)}`, { credentials: "same-origin" });
            const data = await res.json();
            if (this.q.trim() === q) this.results = [...pages, ...data.results];
          } catch (e) { /* offline: keep page matches */ }
          this.loading = false;
        }, 150);
      },
      move(step) {
        const n = this.results.length;
        if (!n) return;
        this.active = (this.active + step + n) % n;
        this.$nextTick(() => this.$refs.list.querySelector(".cmdk-item.active")?.scrollIntoView({ block: "nearest" }));
      },
      go(item) {
        if (!item) return;
        this.open = false;
        startProgress();
        window.location = item.url;
      },
      groupStart(i) { return i === 0 || this.results[i - 1].group !== this.results[i].group; },
    }));

    // Donut: hovering a legend row highlights its slice, and vice versa.
    Alpine.data("donut", () => ({
      hot: null,
      set(i) { this.hot = i; },
      clear() { this.hot = null; },
    }));
  });
})();
