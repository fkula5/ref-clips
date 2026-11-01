// Formularz opisu klipu (strona klipu i ekran opisywania): pole „nazwa własnej kategorii” jest widoczne
// i wymagane tylko dla kategorii „własna”.
(function () {
  const select = document.getElementById("category-select");
  const label = document.getElementById("custom-label");
  if (!select || !label) return;
  const input = label.querySelector("input");
  function sync() {
    const option = select.options[select.selectedIndex];
    const custom = !!option && option.dataset.custom === "1";
    label.classList.toggle("hidden", !custom);
    if (input) input.required = custom;
  }
  select.addEventListener("change", sync);
  sync();
})();
