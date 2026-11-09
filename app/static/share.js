// Udostępnianie klipów linkiem: kopiowanie adresu (strona „Link jest gotowy”) i zaznaczanie klipów na listach.
(function () {
  // Przycisk z data-copy="#selektor" kopiuje wartość pola; bez schowka (np. brak HTTPS) zaznacza tekst do ręcznego skopiowania.
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button) return;
    const input = document.querySelector(button.dataset.copy);
    if (!input) return;
    input.select();
    let ok = false;
    try { await navigator.clipboard.writeText(input.value); ok = true; } catch (e) { /* spróbuj starszą metodą */ }
    if (!ok) { try { ok = document.execCommand("copy"); } catch (e) { ok = false; } }
    button.textContent = ok ? "Skopiowano" : "Zaznaczono — skopiuj ręcznie (Ctrl+C)";
  });

  // Lista klipów: zaznaczenie pamiętamy w zbiorze, bo lista jest podmieniana przez HTMX (filtry, odświeżanie
  // co 3 s) i pola wyboru powstają od nowa. Zaznaczone klipy spoza bieżącego widoku wysyłamy ukrytymi polami.
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
    if (count.textContent !== text) count.textContent = text;   // bez zbędnych zmian: obserwator patrzy na ten sam fragment
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
  for (const box of boxes()) if (box.checked) selected.add(box.value);   // np. po powrocie z historii
  new MutationObserver(sync).observe(document.querySelector("main"), {childList: true, subtree: true});
  sync();
})();
