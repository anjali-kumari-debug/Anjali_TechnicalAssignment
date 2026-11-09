/* Shared helpers for talking to the JSON API. */
"use strict";

const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content || "";

class ApiError extends Error {
  constructor(status, body) {
    const error = (body && body.error) || {};
    super(error.message || `Request failed (HTTP ${status}).`);
    this.status = status;
    this.code = error.code;
    this.details = error.details || [];
  }
}

/**
 * fetch() wrapper: sends JSON + the CSRF header, parses JSON errors into ApiError.
 * If `button` is given it is disabled until the request finishes, so a double click
 * cannot send the same request twice.
 */
async function apiFetch(url, { method = "GET", body, button } = {}) {
  if (button) button.disabled = true;
  try {
    return await sendRequest(url, method, body);
  } catch (error) {
    // Re-enable only on failure. On success the caller navigates away, and the button
    // must stay disabled until the new page loads.
    if (button) button.disabled = false;
    throw error;
  }
}

async function sendRequest(url, method, body) {
  const options = { method, headers: { Accept: "application/json" }, credentials: "same-origin" };
  if (method !== "GET") options.headers["X-CSRFToken"] = CSRF_TOKEN;
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, options);
  } catch (networkError) {
    throw new ApiError(0, { error: { message: "Could not reach the server. Check your connection and try again." } });
  }
  const data = await response.json().catch(() => null);
  if (response.status === 401) {
    window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
  }
  if (!response.ok) throw new ApiError(response.status, data);
  return data;
}

/* Forms with data-confirm="..." ask before submitting (text is read from the attribute,
   never pasted into JavaScript source, so names with quotes are safe). */
document.addEventListener("submit", (event) => {
  const message = event.target.dataset && event.target.dataset.confirm;
  if (message && !window.confirm(message)) event.preventDefault();
});

/* ---- Money: integer paise, never floats. ---- */

/** "1500.5" -> 150050. Returns null for anything that is not a non-negative amount with <= 2 decimals. */
function parsePaise(text) {
  const match = /^(\d{1,10})(?:\.(\d{1,2}))?$/.exec(String(text).trim());
  if (!match) return null;
  return Number(match[1]) * 100 + Number((match[2] || "").padEnd(2, "0"));
}

const INR = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
function formatPaise(paise) {
  return INR.format(paise / 100);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

/** Render an ApiError (message + details list) into a container element. */
function showError(container, error) {
  const items = (error.details || [])
    .map((d) => `<li>${escapeHtml(d.product_code ? `${d.product_code}: ${d.message}` : d.message || String(d))}</li>`)
    .join("");
  container.innerHTML = escapeHtml(error.message) + (items ? `<ul>${items}</ul>` : "");
  container.className = "flash flash-error";
  container.hidden = false;
}
