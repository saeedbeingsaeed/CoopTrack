// Board: drag and drop between stages with SortableJS.
//
// A drop moves the card on screen immediately, then saves in the background
// by POSTing to the same /stage/ endpoint the Move menu uses. If the save
// fails, the card goes back exactly where it came from and an error toast
// explains why. On success the server's events refresh the board, so counts,
// ordering and badges always match the database.

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
    if (!response.ok) throw new Error(response.status === 403 ? "expired" : "server");
    fireServerEvents(response.headers.get("HX-Trigger"));
  } catch (error) {
    // Put the card back where it was, in the same position.
    event.from.insertBefore(card, card.originalNextSibling);
    showToast(
      error.message === "expired"
        ? `Couldn't move ${card.dataset.company}: your session expired. Reload the page.`
        : `Couldn't move ${card.dataset.company}. It's back where it was. Please try again.`,
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
      sort: false, // cards are ordered by deadline; dragging only changes the stage
      draggable: ".board-card",
      filter: ".move-menu", // the ⋯ menu is for clicking, not dragging
      preventOnFilter: false,
      delay: 180, // on touch screens, a short hold starts a drag so swiping still scrolls
      delayOnTouchOnly: true,
      animation: 150,
      ghostClass: "board-ghost",
      chosenClass: "board-chosen",
      onStart: (event) => {
        event.item.originalNextSibling = event.item.nextElementSibling;
        document.body.classList.add("is-dragging");
      },
      onEnd: () => document.body.classList.remove("is-dragging"),
      onAdd: saveMove, // fires on the list the card was dropped into
    });
  });
}

// Keyboard users move cards with the ⋯ menu. The board then refreshes, so put
// focus back on the moved card's menu button instead of losing it.
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
