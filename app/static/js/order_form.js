/* Order create / edit form: dynamic rows, live totals, client-side validation.
 * The server re-validates and recalculates everything; these totals are only a preview. */
"use strict";

(function () {
  const form = document.getElementById("order-form");
  const tbody = document.querySelector("#items tbody");
  const rowTemplate = document.getElementById("row-template");
  const customerSelect = document.getElementById("customer");
  const discountInput = document.getElementById("discount");
  const errorBox = document.getElementById("form-errors");
  const saveButton = document.getElementById("save");
  const orderId = form.dataset.orderId;
  const existingOrder = JSON.parse(form.dataset.order || "{}");

  // product id -> {id, product_code, name, price (string), stock_quantity}
  const products = new Map();
  // For an existing draft, lines keep their stored rate (the server does the same).
  const storedRates = new Map((existingOrder.items || []).map((item) => [item.product_id, item.rate]));

  async function loadProducts() {
    let page = 1;
    let pages = 1;
    do {
      const data = await apiFetch(`/api/products?per_page=100&page=${page}`);
      data.items.forEach((p) => products.set(p.id, p));
      pages = data.pages;
      page += 1;
    } while (page <= pages);
    // Products already on a draft may have been deactivated since; keep them visible.
    (existingOrder.items || []).forEach((item) => {
      if (!products.has(item.product_id)) {
        products.set(item.product_id, {
          id: item.product_id, product_code: item.product_code, name: `${item.product_name} (inactive)`,
          price: item.rate, stock_quantity: null,
        });
      }
    });
  }

  function addRow(productId = "", quantity = 1) {
    const row = rowTemplate.content.firstElementChild.cloneNode(true);
    const select = row.querySelector(".product");
    for (const p of products.values()) {
      const option = new Option(`${p.product_code} · ${p.name}`, p.id);
      select.add(option);
    }
    select.value = productId;
    row.querySelector(".qty").value = quantity;
    tbody.appendChild(row);
    updateRow(row);
  }

  function rateFor(productId) {
    const product = products.get(productId);
    if (!product) return null;
    return parsePaise(storedRates.get(productId) ?? product.price);
  }

  function parseQuantity(text) {
    return /^\d{1,9}$/.test(String(text).trim()) ? Number(text) : null;
  }

  /** Discount as basis points (12.5% -> 1250) so the maths stays in integers. */
  function parseDiscountBp(text) {
    const value = String(text).trim();
    if (value === "") return 0;
    const match = /^(\d{1,2})(?:\.(\d{1,2}))?$/.exec(value);
    if (!match) return null;
    const bp = Number(match[1]) * 100 + Number((match[2] || "").padEnd(2, "0"));
    return bp <= 2000 ? bp : null;
  }

  function updateRow(row) {
    const productId = Number(row.querySelector(".product").value) || null;
    const product = productId ? products.get(productId) : null;
    const rate = productId ? rateFor(productId) : null;
    const quantity = parseQuantity(row.querySelector(".qty").value);
    row.querySelector(".price").textContent = rate === null ? "–" : formatPaise(rate);
    row.querySelector(".stock").textContent = product && product.stock_quantity !== null ? product.stock_quantity : "–";
    row.querySelector(".amount").textContent = rate !== null && quantity ? formatPaise(rate * quantity) : "–";
  }

  function recalculate() {
    let subtotal = 0;
    tbody.querySelectorAll("tr").forEach((row) => {
      updateRow(row);
      const productId = Number(row.querySelector(".product").value) || null;
      const quantity = parseQuantity(row.querySelector(".qty").value);
      const rate = productId ? rateFor(productId) : null;
      if (rate !== null && quantity) subtotal += rate * quantity;
    });
    const bp = parseDiscountBp(discountInput.value) ?? 0;
    // Round half up, same rule as the server (values are never negative here).
    const discount = Math.floor((subtotal * bp + 5000) / 10000);
    document.getElementById("subtotal").textContent = formatPaise(subtotal);
    document.getElementById("discount-amount").textContent = formatPaise(discount);
    document.getElementById("grand-total").textContent = formatPaise(subtotal - discount);
  }

  function clearErrors() {
    errorBox.hidden = true;
    form.querySelectorAll(".invalid").forEach((el) => el.classList.remove("invalid"));
    form.querySelectorAll("[data-error-for], .row-error").forEach((el) => (el.textContent = ""));
  }

  function setFieldError(field, message) {
    const rowMatch = /^items\[(\d+)\]\.(\w+)$/.exec(field);
    if (rowMatch) {
      const row = tbody.querySelectorAll("tr")[Number(rowMatch[1])];
      if (row) {
        row.querySelector(rowMatch[2] === "quantity" ? ".qty" : ".product").classList.add("invalid");
        const box = row.querySelector(".row-error");
        box.textContent = box.textContent ? `${box.textContent} ${message}` : message;
        return;
      }
    }
    const target = form.querySelector(`[data-error-for="${field}"]`) || form.querySelector('[data-error-for="items"]');
    target.textContent = message;
    if (field === "customer_id") customerSelect.classList.add("invalid");
    if (field === "discount_percentage") discountInput.classList.add("invalid");
  }

  /** Client-side checks (the server repeats all of them). Returns a list of {field, message}. */
  function validate() {
    const errors = [];
    if (!customerSelect.value) errors.push({ field: "customer_id", message: "Select a customer." });
    if (parseDiscountBp(discountInput.value) === null) {
      errors.push({ field: "discount_percentage", message: "Discount must be a number from 0 to 20 (max 2 decimals)." });
    }
    const rows = tbody.querySelectorAll("tr");
    if (rows.length === 0) errors.push({ field: "items", message: "Add at least one item." });
    const seen = new Set();
    rows.forEach((row, index) => {
      const productId = row.querySelector(".product").value;
      const quantity = parseQuantity(row.querySelector(".qty").value);
      if (!productId) errors.push({ field: `items[${index}].product_id`, message: "Select a product." });
      else if (seen.has(productId)) errors.push({ field: `items[${index}].product_id`, message: "This product is already in the order." });
      else seen.add(productId);
      if (!quantity) errors.push({ field: `items[${index}].quantity`, message: "Quantity must be a whole number greater than 0." });
    });
    return errors;
  }

  function payload() {
    return {
      customer_id: Number(customerSelect.value),
      discount_percentage: discountInput.value.trim() || "0",
      items: [...tbody.querySelectorAll("tr")].map((row) => ({
        product_id: Number(row.querySelector(".product").value),
        quantity: Number(row.querySelector(".qty").value),
      })),
    };
  }

  async function save(event) {
    event.preventDefault();
    clearErrors();
    const errors = validate();
    if (errors.length) {
      errors.forEach((e) => setFieldError(e.field, e.message));
      showError(errorBox, { message: "Please correct the highlighted fields.", details: [] });
      return;
    }
    try {
      const order = await apiFetch(orderId ? `/api/orders/${orderId}` : "/api/orders", {
        method: orderId ? "PUT" : "POST",
        body: payload(),
        button: saveButton,
      });
      window.location.href = `/orders/${order.id}`;
    } catch (error) {
      (error.details || []).forEach((d) => d.field && setFieldError(d.field, d.message));
      showError(errorBox, error);
    }
  }

  tbody.addEventListener("change", recalculate);
  tbody.addEventListener("input", recalculate);
  tbody.addEventListener("click", (event) => {
    if (event.target.classList.contains("remove-row")) {
      event.target.closest("tr").remove();
      recalculate();
    }
  });
  discountInput.addEventListener("input", recalculate);
  document.getElementById("add-row").addEventListener("click", () => addRow());
  form.addEventListener("submit", save);

  loadProducts()
    .then(() => {
      const items = existingOrder.items || [];
      if (items.length) items.forEach((item) => addRow(item.product_id, item.quantity));
      else addRow();
      recalculate();
    })
    .catch((error) => showError(errorBox, error));
})();
