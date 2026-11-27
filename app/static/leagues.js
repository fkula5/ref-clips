// Renaming a league to the name of another one merges them: ask first, and tell the server it was confirmed.
(function () {
  function norm(text) {
    return text.replace(/ł/g, 'l').replace(/Ł/g, 'L').normalize('NFKD').replace(/[̀-ͯ]/g, '')
      .toLowerCase().replace(/\s+/g, ' ').trim();
  }

  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!form.matches || !form.matches('form[data-league-others]')) return;
    var typed = form.elements.namedItem('name').value;
    var others = JSON.parse(form.dataset.leagueOthers);
    var old = JSON.parse(form.dataset.leagueOld);
    var other = others.find(function (name) { return norm(name) === norm(typed); });
    var merge = form.elements.namedItem('merge');
    merge.value = '0';
    if (!other) return;
    var ok = confirm('Liga „' + other + '” już istnieje. Połączyć? Mecze ligi „' + old +
      '” zostaną przeniesione do „' + other + '”, a „' + old + '” zostanie usunięta.');
    if (ok) merge.value = '1'; else event.preventDefault();
  });
})();
