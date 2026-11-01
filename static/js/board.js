// Drag and drop with SortableJS. The card moves right away and saves in the
// background; if the save fails it goes back and a toast says why.
// csrfToken() and fireServerEvents() are in app.js.

async function saveMove(event) {
  const card = event.item;
  const stage = event.to.dataset.stage;
  card.setAttribute("aria-busy", "true");
  card.classList.add("opacity-60");
  try {
    const response = await fetch(card.dataset.moveUrl, {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken(), "HX-Request": "true" },
      body: new URLSearchParams({ to: stage }),
    });
    if (response.status === 409) throw new Error(await response.text());
    if (!response.ok) throw new Error(response.status === 403 ? "expired" : "server");
    fireServerEvents(response.headers.get("HX-Trigger"));
  } catch (error) {
    event.from.insertBefore(card, card.originalNextSibling);
    showToast(
      error.message === "expired"
        ? `Couldn't move ${card.dataset.company}: your session expired. Reload the page.`
        : error.message === "server"
          ? `Couldn't move ${card.dataset.company}. It's back where it was. Please try again.`
          : error.message,
      "error",
    );
  } finally {
    card.removeAttribute("aria-busy");
    card.classList.remove("opacity-60");
  }
}

function initBoard(root) {
  root.querySelectorAll("[data-board-list]").forEach((list) => {
    if (Sortable.get(list)) return;
    Sortable.create(list, {
      group: "board",
      sort: false, // cards are sorted by deadline
      draggable: ".board-card",
      filter: ".move-menu",
      preventOnFilter: false,
      delay: 180, // hold to drag on touch screens, so swiping still scrolls
      delayOnTouchOnly: true,
      animation: 150,
      ghostClass: "board-ghost",
      chosenClass: "board-chosen",
      onStart: (event) => {
        event.item.originalNextSibling = event.item.nextElementSibling;
        document.body.classList.add("is-dragging");
      },
      onEnd: () => document.body.classList.remove("is-dragging"),
      onAdd: saveMove,
    });
  });
}

// After moving with the ⋯ menu the board reloads, so put focus back on that card's menu.
let focusAfterRefresh = null;
document.addEventListener("htmx:beforeRequest", (event) => {
  const form = event.detail.elt.closest?.("[data-move-form]");
  if (form) focusAfterRefresh = `move-${form.dataset.cardId}`;
});

htmx.onLoad((root) => {
  initBoard(root);
  if (focusAfterRefresh && root.id === "board") {
    document.getElementById(focusAfterRefresh)?.focus();
    focusAfterRefresh = null;
  }
});
