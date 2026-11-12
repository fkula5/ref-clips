// Early feedback only: the server validates type, size and count again.
(() => {
  const form = document.getElementById("scoresheet-form");
  if (!form) return;
  const input = document.getElementById("scoresheet-files");
  const error = document.getElementById("scoresheet-client-error");
  const maxBytes = Number(form.dataset.maxBytes), maxFiles = Number(form.dataset.maxFiles);
  const existing = Number(form.dataset.existing);

  const problem = () => {
    const files = Array.from(input.files);
    if (existing + files.length > maxFiles) {
      return `Przy meczu może być najwyżej ${maxFiles} plików protokołu (zostało miejsca na: ${Math.max(0, maxFiles - existing)}).`;
    }
    const big = files.find((f) => f.size > maxBytes);
    return big ? `„${big.name}”: plik jest za duży (maksymalnie ${Math.floor(maxBytes / 1048576)} MB).` : "";
  };
  const show = (text) => { error.textContent = text; error.hidden = !text; };

  input.addEventListener("change", () => show(problem()));
  form.addEventListener("submit", (event) => {
    const text = problem();
    show(text);
    if (text) { event.preventDefault(); return; }
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = "Wysyłanie…";
  });
  // Back/forward cache restores the page with the button still disabled.
  window.addEventListener("pageshow", () => {
    const button = form.querySelector("button[type=submit]");
    button.disabled = false;
    button.textContent = "Dodaj do protokołu";
  });
})();
