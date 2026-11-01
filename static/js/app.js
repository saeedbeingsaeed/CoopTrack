// Small behaviours shared by every page. No framework, no build step.

// Flash messages: dismiss on click, and fade out on their own after a while.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-dismiss]");
  if (button) button.closest(".toast")?.remove();
});

function autoDismissToasts() {
  document.querySelectorAll("#messages .toast:not([data-timer])").forEach((toast) => {
    toast.dataset.timer = "1";
    setTimeout(() => toast.remove(), 6000);
  });
}
document.addEventListener("DOMContentLoaded", autoDismissToasts);
document.addEventListener("htmx:afterSettle", autoDismissToasts);

// Close an open <details> dropdown when clicking elsewhere or pressing Escape.
document.addEventListener("click", (event) => {
  document.querySelectorAll("details[open]").forEach((menu) => {
    if (!menu.contains(event.target)) menu.removeAttribute("open");
  });
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  document.querySelectorAll("details[open]").forEach((menu) => {
    menu.removeAttribute("open");
    menu.querySelector("summary")?.focus();
  });
});

// Show the top progress bar for any HTMX request, wherever it starts.
document.addEventListener("htmx:beforeRequest", () => document.getElementById("page-progress")?.classList.add("htmx-request"));
document.addEventListener("htmx:afterRequest", () => document.getElementById("page-progress")?.classList.remove("htmx-request"));

// Server-sent toasts: views reply with an HX-Trigger header like {"toast": {"message": "..."}}.
// After a move it also has "undo_url", which adds an Undo button.
document.addEventListener("toast", (event) => showToast(event.detail.message, "info", event.detail.undo_url));

function csrfToken() {
  return JSON.parse(document.body.getAttribute("hx-headers"))["X-CSRFToken"];
}

// Fire the events named in an HX-Trigger header, the same way HTMX would.
function fireServerEvents(header) {
  if (!header) return;
  for (const [name, detail] of Object.entries(JSON.parse(header))) {
    document.body.dispatchEvent(new CustomEvent(name, { bubbles: true, detail }));
  }
}
window.csrfToken = csrfToken;
window.fireServerEvents = fireServerEvents;

async function undoMove(url, toast) {
  toast.remove();
  try {
    const response = await fetch(url, { method: "POST", headers: { "X-CSRFToken": csrfToken(), "HX-Request": "true" } });
    if (!response.ok) throw new Error(response.status === 409 ? await response.text() : "Couldn't undo. Please try again.");
    fireServerEvents(response.headers.get("HX-Trigger"));
  } catch (error) {
    showToast(error.message, "error");
  }
}

// A control that saves on change (data-current holds the saved value) goes back
// to that value if the save fails, so the page never shows something unsaved.
document.addEventListener("htmx:afterRequest", (event) => {
  const control = event.detail.elt;
  if (!("current" in control.dataset)) return;
  if (event.detail.successful) control.dataset.current = control.value;
  else control.value = control.dataset.current;
});

// A failed HTMX request should never fail silently. A 409 comes with its own message.
document.addEventListener("htmx:responseError", (event) => {
  const xhr = event.detail.xhr;
  const text =
    xhr.status === 403 ? "Your session expired. Reload the page and try again."
    : xhr.status === 409 ? xhr.responseText
    : "Something went wrong. Please try again.";
  showToast(text, "error");
});
document.addEventListener("htmx:sendError", () => showToast("Can't reach the server. Check your connection and try again.", "error"));

function showToast(text, level, undoUrl) {
  const container = document.getElementById("messages");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className =
    "toast pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border px-4 py-3 text-sm shadow-lg " +
    (level === "error"
      ? "border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-100"
      : "border-zinc-200 bg-white text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100");
  const message = document.createElement("p");
  message.className = "flex-1";
  message.textContent = text;
  toast.append(message);
  if (undoUrl) {
    const undo = document.createElement("button");
    undo.type = "button";
    undo.className = "shrink-0 font-semibold text-brand-700 hover:underline dark:text-brand-300";
    undo.textContent = "Undo";
    undo.addEventListener("click", () => undoMove(undoUrl, toast));
    toast.append(undo);
  }
  container.append(toast);
  autoDismissToasts();
}
window.showToast = showToast;

// Buttons that start slow work (like setting up the demo) say so and can't be double-clicked.
document.addEventListener("submit", (event) => {
  const button = event.target.querySelector("[data-loading-text]");
  if (!button) return;
  button.dataset.originalHtml = button.innerHTML;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = button.dataset.loadingText;
});
// Coming back with the browser's Back button can restore the page as it was left; reset those buttons.
window.addEventListener("pageshow", () => {
  document.querySelectorAll("[data-loading-text][aria-busy]").forEach((button) => {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.innerHTML = button.dataset.originalHtml;
  });
});
