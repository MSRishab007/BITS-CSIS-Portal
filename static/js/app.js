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

  // Two harmless rejections happen when a page swap interrupts an animation:
  //  - Alpine: a closing x-transition was cut short ({isFromCancelledTransition})
  //  - browser: a page transition was skipped because a new load started
  // Swallow just these so real errors stand out in the console.
  window.addEventListener("unhandledrejection", (e) => {
    const r = e.reason;
    const benign = (r && r.isFromCancelledTransition) ||
      (typeof DOMException !== "undefined" && r instanceof DOMException &&
       ["AbortError", "InvalidStateError"].includes(r.name));
    if (benign) e.preventDefault();
  });
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
    if (a.closest("[hx-boost='true']") && !a.closest("[hx-boost='false']")) return;  // htmx shows its own progress
    if (a.origin === location.origin) startProgress();
  });
  document.addEventListener("submit", (e) => {
    if (e.target.closest("[hx-boost='true']") && !e.target.closest("[hx-boost='false']")) return;
    if (!e.defaultPrevented) startProgress();
  });
  function finishProgress() {
    const bar = document.querySelector(".nav-progress");
    if (bar) { bar.classList.remove("run"); bar.classList.add("done"); }
  }
  window.addEventListener("pageshow", finishProgress);

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
  function placeNav(nav, link, animate = true) {
    const ind = nav.querySelector(".nav-indicator");
    if (!ind) return;
    if (!animate) ind.style.transition = "none";
    placeThumb(nav, ind, link || nav.querySelector(".nav-link.active"), true);
    if (!animate) { void ind.offsetWidth; ind.style.transition = ""; }
  }
  function bindNav(nav) {
    if (nav.dataset.bound) { placeNav(nav); return; }
    nav.dataset.bound = "1";
    placeNav(nav, null, false);
    // Slide immediately on click (instant feedback); corrected after the swap.
    nav.addEventListener("click", (e) => {
      const link = e.target.closest(".nav-link");
      if (link && !e.metaKey && !e.ctrlKey) placeNav(nav, link);
    });
  }

  // Underline that slides between tabs (Lists & fields).
  function bindTabs(tabs) {
    let ink = tabs.querySelector(".tab-ink");
    if (!ink) { ink = document.createElement("span"); ink.className = "tab-ink"; tabs.appendChild(ink); }
    const active = tabs.querySelector(".tab.active");
    const prev = sessionStorage.getItem("tab-ink");
    const place = (el, animate) => {
      if (!el) return;
      if (!animate) ink.style.transition = "none";
      ink.style.transform = `translateX(${el.offsetLeft}px)`;
      ink.style.width = `${el.offsetWidth}px`;
      if (!animate) { void ink.offsetWidth; ink.style.transition = ""; }
    };
    if (prev && active && !reduceMotion) {        // start where the last tab was, then slide
      const [x, w] = prev.split(",");
      ink.style.transition = "none"; ink.style.transform = `translateX(${x}px)`; ink.style.width = `${w}px`;
      void ink.offsetWidth; ink.style.transition = "";
      requestAnimationFrame(() => place(active, true));
    } else place(active, false);
    tabs.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
      sessionStorage.setItem("tab-ink", `${t.offsetLeft},${t.offsetWidth}`);
      place(t, true);
    }));
  }

  function init(root = document) {
    root.querySelectorAll(".tilt").forEach(bindTilt);
    root.querySelectorAll(".segmented").forEach(bindSegmented);
    document.querySelectorAll(".nav").forEach(bindNav);
    root.querySelectorAll(".tabs").forEach(bindTabs);
    const counters = root.querySelectorAll("[data-count]");
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver((entries) => entries.forEach((en) => {
        if (en.isIntersecting) { countUp(en.target); io.unobserve(en.target); }
      }), { threshold: 0.3 });
      counters.forEach((c) => io.observe(c));
    } else counters.forEach(countUp);
  }
  document.addEventListener("DOMContentLoaded", () => init());
  window.addEventListener("resize", () => document.querySelectorAll(".nav").forEach((n) => placeNav(n, null, false)));

  // ---------------------------------------------------------------- htmx (smooth navigation)
  // Only #content (and the nav links) are swapped; the sidebar stays put.
  document.addEventListener("htmx:beforeRequest", (e) => {
    if (e.detail.boosted) startProgress();
    const form = e.detail.elt.tagName === "FORM" ? e.detail.elt : null;
    const btn = form && (lastSubmitter || form.querySelector("button[type=submit]:not([formnovalidate])"));
    if (btn && form.contains(btn)) btn.classList.add("is-loading");
  });
  let lastSubmitter = null;
  document.addEventListener("submit", (e) => { lastSubmitter = e.submitter || null; }, true);

  document.addEventListener("htmx:beforeSwap", (e) => {
    const xhr = e.detail.xhr;
    if (!e.detail.boosted || !xhr) return;
    // Not an app page (sign-in, technical admin, a server error page…): load it normally.
    if (!/id="content"/.test(xhr.responseText || "")) {
      e.preventDefault();
      window.location.href = xhr.responseURL || e.detail.pathInfo.requestPath;
    }
  });
  document.addEventListener("htmx:afterSettle", (e) => {
    finishProgress();
    lastSubmitter = null;
    if (e.detail.target && e.detail.target.id === "content") {
      init(document.getElementById("content") || document);
      window.dispatchEvent(new CustomEvent("navigated"));
    }
  });
  ["htmx:sendError", "htmx:timeout"].forEach((ev) => document.addEventListener(ev, (e) => {
    // Network trouble: fall back to a normal page load.
    finishProgress();
    if (e.detail.requestConfig && e.detail.requestConfig.verb === "get") window.location.href = e.detail.pathInfo.requestPath;
  }));

  // Navigate with the same smooth swap from code (e.g. the command menu).
  // One permanent hidden link inside the boosted shell: htmx reads its
  // inherited settings (target/select) when the response arrives, so it must
  // still be in the page then — never create-and-remove it.
  window.portalNavigate = function (url) {
    const app = document.querySelector(".app[hx-boost]");
    if (!window.htmx || !app) { window.location = url; return; }
    let a = document.getElementById("portal-nav-link");
    if (!a) {
      a = document.createElement("a");
      a.id = "portal-nav-link"; a.hidden = true; a.setAttribute("aria-hidden", "true");
      app.appendChild(a);
    }
    a.setAttribute("href", url);
    htmx.process(a);
    a.click();
  };

  // ---------------------------------------------------------------- Alpine components
  document.addEventListener("alpine:init", () => {
    // Sidebar: open on mobile, collapse on desktop (remembered per browser).
    Alpine.data("shell", () => ({
      nav: false,
      collapsed: false,
      init() {
        window.addEventListener("navigated", () => { this.nav = false; });
        try { this.collapsed = localStorage.getItem("sidebar-collapsed") === "1"; } catch (e) { /* storage off */ }
        this.$watch("collapsed", (v) => {
          try { localStorage.setItem("sidebar-collapsed", v ? "1" : "0"); } catch (e) { /* storage off */ }
          setTimeout(() => document.querySelectorAll(".nav").forEach((n) => placeNav(n, null, false)), 260);
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
          // The input lives inside x-if, so wait until it exists.
          requestAnimationFrame(() => document.querySelector(".cmdk-input input")?.focus()); }
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
        window.portalNavigate(item.url);
      },
      groupStart(i) { return i === 0 || this.results[i - 1].group !== this.results[i].group; },
    }));

    // Row action menu (⋯). Positioned against the window so table scrolling can't clip it.
    Alpine.data("menu", () => ({
      o: false, x: 0, y: 0,
      toggle() {
        if (this.o) { this.o = false; return; }
        const r = this.$refs.btn.getBoundingClientRect();
        this.x = Math.max(8, r.right - 200);
        this.y = r.bottom + 6;
        if (this.y + 180 > window.innerHeight) this.y = r.top - 6 - 150;
        this.o = true;
      },
      init() { window.addEventListener("scroll", () => (this.o = false), { passive: true }); },
    }));

    // Slide-over preview of an invoice (purchase list).
    Alpine.data("peek", () => ({
      open: false, loading: false, html: "", openId: null,
      async show(id, url) {
        this.openId = id; this.open = true; this.loading = true;
        try {
          const res = await fetch(url, { credentials: "same-origin" });
          this.html = res.ok ? await res.text() : "<p class='muted'>Couldn't load this invoice.</p>";
        } catch (e) { this.html = "<p class='muted'>Couldn't load this invoice.</p>"; }
        this.loading = false;
        this.$nextTick(() => {
          document.querySelectorAll(".drawer a[href]:not([target])").forEach((a) =>
            a.addEventListener("click", (ev) => { ev.preventDefault(); this.close(); window.portalNavigate(a.getAttribute("href")); }, { once: true }));
        });
      },
      close() { this.open = false; this.openId = null; },
    }));

    // Donut: hovering a legend row highlights its slice, and vice versa.
    Alpine.data("donut", () => ({
      hot: null,
      set(i) { this.hot = i; },
      clear() { this.hot = null; },
    }));
  });
})();
