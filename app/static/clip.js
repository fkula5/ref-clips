// Strona klipu: pole „nazwa własnej kategorii” widoczne tylko dla kategorii „własna”.
(function () {
  const select = document.getElementById("category-select");
  const label = document.getElementById("custom-label");
  if (!select || !label) return;
  function sync() {
    const option = select.options[select.selectedIndex];
    label.classList.toggle("hidden", !(option && option.dataset.custom === "1"));
  }
  select.addEventListener("change", sync);
  sync();
})();
