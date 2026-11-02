// Oceny i komentarze (HTMX): odpowiedź 422 to błąd walidacji z formularzem do podmiany (domyślnie HTMX
// nie podmienia treści przy kodach 4xx); inne błędy (np. komentarz usunięty przez kogoś w międzyczasie,
// brak uprawnień, brak sieci) pokazują krótki komunikat zamiast cichej bezczynności.
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
    try { message = JSON.parse(event.detail.xhr.responseText).detail || message; } catch (e) { /* nie JSON */ }
    toast(message);
  });

  document.body.addEventListener("htmx:sendError", (event) => {
    if (inFeedback(event.detail.elt)) toast("Brak połączenia z serwerem — spróbuj ponownie.");
  });
})();
