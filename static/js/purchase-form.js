/* Behaviour for the purchase entry form (Alpine.js components).
 *
 *   vendorPicker   – search existing vendors, or type a new name
 *   invoicePicker  – shows YOUR past invoices; picking one opens "add items"
 *   purchaseForm   – add/remove item rows, live totals
 *   itemRow        – type list follows category, project fields follow funding,
 *                    custom fields follow category
 *
 * Initial values are read from data-* attributes (HTML-escaped by Django),
 * never written into script text.
 */
(function () {
  const formData = () => JSON.parse(document.getElementById("form-data").textContent);

  async function getJSON(url) {
    const res = await fetch(url, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" });
    if (!res.ok) throw new Error(res.status);
    return res.json();
  }

  // Shared keyboard handling for a dropdown list.
  const listKeys = {
    move(step) {
      if (!this.open) { this.open = true; return; }
      const n = this.optionCount();
      if (n) this.active = (this.active + step + n) % n;
    },
  };

  document.addEventListener("alpine:init", () => {
    // ------------------------------------------------------------------
    Alpine.data("vendorPicker", () => ({
      ...listKeys,
      query: "", id: "", chosenName: "", results: [], exact: null,
      open: false, active: -1, loading: false, url: "",

      init() {
        const d = this.$el.dataset;
        this.url = d.url;
        this.query = d.initialName || "";
        this.id = d.initialId || "";
        this.chosenName = this.id ? this.query : "";
      },
      get showCreate() { return this.query.trim() !== "" && !this.exact; },
      optionCount() { return this.results.length + (this.showCreate ? 1 : 0); },

      async search() {
        this.loading = true;
        try {
          const data = await getJSON(`${this.url}?q=${encodeURIComponent(this.query.trim())}`);
          this.results = data.results;
          this.exact = data.exact;
          this.active = this.results.length ? 0 : (this.showCreate ? 0 : -1);
        } catch (e) { this.results = []; }
        this.loading = false;
      },
      onInput() {
        if (this.query !== this.chosenName) this.id = "";   // edited after picking
        this.open = true;
        this.search();
      },
      choose(v) {
        this.id = String(v.id); this.query = v.name; this.chosenName = v.name;
        this.open = false;
      },
      chooseNew() { this.id = ""; this.chosenName = ""; this.open = false; },
      enter(e) {
        if (!this.open || this.active < 0) return;
        e.preventDefault();
        if (this.active < this.results.length) this.choose(this.results[this.active]);
        else this.chooseNew();
      },
      blur() {
        // Typed text exactly matches an existing vendor: use it.
        if (!this.id && this.exact) this.choose(this.exact);
        setTimeout(() => (this.open = false), 150);
      },
    }));

    // ------------------------------------------------------------------
    Alpine.data("invoicePicker", () => ({
      ...listKeys,
      query: "", results: [], open: false, active: -1, url: "", ownerField: null,

      init() {
        const d = this.$el.dataset;
        this.url = d.url;
        this.query = d.initial || "";
        this.ownerField = d.ownerField ? document.getElementById(d.ownerField) : null;
        if (this.ownerField) this.ownerField.addEventListener("change", () => { this.results = []; });
      },
      optionCount() { return this.results.length; },
      get duplicate() {
        const q = this.query.trim().toLowerCase();
        return q && this.results.find((r) => r.invoice_number.toLowerCase() === q);
      },
      async search() {
        const owner = this.ownerField && this.ownerField.value ? `&owner=${this.ownerField.value}` : "";
        try {
          const data = await getJSON(`${this.url}?q=${encodeURIComponent(this.query.trim())}${owner}`);
          this.results = data.results;
          this.active = -1;
        } catch (e) { this.results = []; }
      },
      enter(e) {
        if (this.open && this.active >= 0 && this.results[this.active]) {
          e.preventDefault();
          window.location = this.results[this.active].add_items_url;
        }
      },
    }));

    // ------------------------------------------------------------------
    Alpine.data("purchaseForm", () => ({
      itemCount: 0, itemsTotal: 0, billAmount: null, submitting: false,

      init() { this.$nextTick(() => this.recalc()); },
      addRow() {
        const total = document.getElementById("id_items-TOTAL_FORMS");
        const index = parseInt(total.value, 10);
        const html = this.$refs.emptyItem.innerHTML.replaceAll("__prefix__", index);
        this.$refs.rows.insertAdjacentHTML("beforeend", html);
        total.value = index + 1;
        this.$nextTick(() => {
          const row = this.$refs.rows.lastElementChild;
          row.scrollIntoView({ behavior: "smooth", block: "center" });
          const first = row.querySelector("select, input:not([type=hidden])");
          if (first) first.focus({ preventScroll: true });
          this.recalc();
        });
      },
      recalc() {
        const rows = [...this.$refs.rows.querySelectorAll(".item-wrap")]
          .filter((r) => !r.querySelector('input[name$="-DELETE"]')?.checked);
        this.itemCount = rows.length;
        this.itemsTotal = rows.reduce((sum, r) => {
          const v = parseFloat(r.querySelector('input[name$="-amount"]')?.value);
          return sum + (isNaN(v) ? 0 : v);
        }, 0);
        const bill = document.getElementById("id_bill_amount");
        const b = bill ? parseFloat(bill.value) : parseFloat(this.$el.dataset.billAmount);
        this.billAmount = isNaN(b) ? null : b;
      },
      money(n) {
        return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      },
    }));

    // ------------------------------------------------------------------
    Alpine.data("itemRow", () => ({
      category: "", type: "", funding: "", name: "", deleted: false, more: false, data: null,

      init() {
        const d = this.$el.dataset;
        this.data = formData();
        this.category = d.category || "";
        this.type = d.type || "";
        this.funding = d.funding || "";
        this.name = d.name || "";
        this.deleted = d.deleted === "true";
        this.more = d.more === "true";
        this.$watch("category", () => {
          if (!this.types.some((t) => String(t.id) === this.type)) this.type = "";
        });
        this.$watch("deleted", () => this.$dispatch("recalc"));
      },
      get types() {
        const c = this.data.categories.find((c) => String(c.id) === this.category);
        return c ? c.types : [];
      },
      get needsProject() {
        return this.data.project_funding_ids.map(String).includes(this.funding);
      },
      showField(key) {
        const cats = this.data.item_field_categories[key] || [];
        return cats.length === 0 || cats.map(String).includes(this.category);
      },
    }));
  });
})();
