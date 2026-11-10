// HTMX does not swap content on 4xx by default: 422 is a validation error with a form to swap in. Other
// errors (e.g. comment deleted meanwhile, no permission, no network) show a short message instead of
// silent inaction.
(function () {
  function inFeedback(elt) {
    return !!(elt && elt.closest && elt.closest("#komentarze, #oceny"));
  }

  function toast(text) {
    const box = document.createElement("div");
    box.className = "toast error";
    box.setAttribute("role", "alert");
    box.textContent = text;
    document.body.appendChild(box);
    setTimeout(() => box.remove(), 5000);
  }

  document.body.addEventListener("htmx:beforeSwap", (event) => {
    if (event.detail.xhr.status === 422 && inFeedback(event.detail.requestConfig.elt)) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });

  document.body.addEventListener("htmx:responseError", (event) => {
    if (!inFeedback(event.detail.elt)) return;
    let message = "Nie udało się wykonać operacji.";
    try { message = JSON.parse(event.detail.xhr.responseText).detail || message; } catch (e) { /* not JSON */ }
    toast(message);
  });

  document.body.addEventListener("htmx:sendError", (event) => {
    if (inFeedback(event.detail.elt)) toast("Brak połączenia z serwerem — spróbuj ponownie.");
  });
})();
