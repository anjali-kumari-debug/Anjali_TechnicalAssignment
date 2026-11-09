/* Confirm / cancel buttons on the order page. */
"use strict";

(function () {
  const actions = document.getElementById("order-actions");
  const resultBox = document.getElementById("action-result");
  if (!actions) return;
  const orderId = actions.dataset.orderId;
  const orderNumber = actions.dataset.orderNumber;

  const prompts = {
    confirm: `Confirm order ${orderNumber}? Stock will be deducted and the order becomes read-only.`,
    cancel: `Cancel order ${orderNumber}? If it was confirmed, its stock will be restored.`,
  };

  actions.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    if (!window.confirm(prompts[action])) return;
    // Disable every action button while the request runs (prevents double submission).
    const buttons = actions.querySelectorAll("button");
    buttons.forEach((b) => (b.disabled = true));
    try {
      await apiFetch(`/api/orders/${orderId}/${action}`, { method: "POST" });
      window.location.reload();
    } catch (error) {
      showError(resultBox, error);
      buttons.forEach((b) => (b.disabled = false));
    }
  });
})();
