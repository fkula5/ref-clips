// Formularze filtrów z atrybutem data-clean-params wysyłane przez HTMX nie niosą pustych pól,
// więc adres po filtrowaniu jest czysty (np. ?period=Q2 zamiast ?person=&category_id=&period=Q2&described=).
document.addEventListener("htmx:configRequest", (event) => {
  const source = event.detail.elt;
  if (!source || !source.closest || !source.closest("[data-clean-params]")) return;
  for (const [name, value] of Array.from(event.detail.formData.entries())) {
    if (value === "") event.detail.formData.delete(name);
  }
});
