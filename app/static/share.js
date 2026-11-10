(function () {
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button) return;
    const input = document.querySelector(button.dataset.copy);
    if (!input) return;
    input.select();
    let ok = false;
    try { await navigator.clipboard.writeText(input.value); ok = true; } catch (e) { /* fall back to the older method */ }
    if (!ok) { try { ok = document.execCommand("copy"); } catch (e) { ok = false; } }
    button.textContent = ok ? "Skopiowano" : "Zaznaczono — skopiuj ręcznie (Ctrl+C)";
  });

  // The selection is kept in a set because the list is replaced by HTMX (filters, 3 s refresh) and the
  // checkboxes are recreated. Selected clips outside the current view are sent as hidden fields.
  const form = document.getElementById("share-form");
  if (!form) return;
  const count = document.getElementById("share-count");
  const submit = document.getElementById("share-submit");
  const max = parseInt(form.dataset.max, 10) || 30;
  const selected = new Set();
  const boxes = () => document.querySelectorAll(".share-check");

  function sync() {
    for (const box of boxes()) box.checked = selected.has(box.value);
    form.classList.toggle("hidden", boxes().length === 0 && selected.size === 0);
    const tooMany = selected.size > max;
    const text = tooMany ? `Zaznaczono: ${selected.size} (najwyżej ${max} w jednym linku)` : `Zaznaczono: ${selected.size}`;
    if (count.textContent !== text) count.textContent = text;  // no needless changes: the observer watches the same fragment
    count.classList.toggle("error-text", tooMany);
    submit.disabled = selected.size === 0 || tooMany;
  }

  document.addEventListener("change", (event) => {
    const box = event.target;
    if (!box.matches || !box.matches(".share-check")) return;
    if (box.checked) selected.add(box.value); else selected.delete(box.value);
    sync();
  });
  form.addEventListener("submit", () => {
    form.querySelectorAll("input.share-extra").forEach((input) => input.remove());
    const visible = new Set(Array.from(boxes()).map((box) => box.value));
    for (const id of selected) {
      if (visible.has(id)) continue;
      const input = document.createElement("input");
      input.type = "hidden"; input.name = "clip_ids"; input.value = id; input.className = "share-extra";
      form.appendChild(input);
    }
  });
  for (const box of boxes()) if (box.checked) selected.add(box.value);  // e.g. after returning from history
  new MutationObserver(sync).observe(document.querySelector("main"), {childList: true, subtree: true});
  sync();
})();
