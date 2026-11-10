// HTMX forms with data-clean-params send no empty fields, so the URL stays clean (e.g. ?period=Q2
// instead of ?person=&category_id=&period=Q2&described=).
document.addEventListener("htmx:configRequest", (event) => {
  const source = event.detail.elt;
  if (!source || !source.closest || !source.closest("[data-clean-params]")) return;
  for (const [name, value] of Array.from(event.detail.formData.entries())) {
    if (value === "") event.detail.formData.delete(name);
  }
});
