(() => {
  const form = document.getElementById("sheet-form");
  if (!form) return;

  const fields = () => [...form.querySelectorAll("textarea")];
  const state = () => JSON.stringify([...new FormData(form)].filter(([key]) => key !== "csrf_token" && key !== "action"));
  const saved = state();
  // After a failed save the form shows what the user typed, which is not stored yet.
  const startedDirty = form.dataset.unsaved === "1";
  let submitting = false;

  const isDirty = () => !submitting && (startedDirty || state() !== saved);

  window.addEventListener("beforeunload", (event) => {
    if (!isDirty()) return;
    event.preventDefault();
    event.returnValue = "";  // required by some browsers to show the prompt
  });

  window.addEventListener("pageshow", () => { submitting = false; });  // page restored from the back/forward cache

  form.addEventListener("submit", (event) => {
    const action = event.submitter && event.submitter.value;
    if (action === "publish" && form.elements.difficulty.value) {
      const all = fields();
      const empty = all.filter((field) => !field.value.trim()).length;
      const message = `Opublikować arkusz? Puste pola: ${empty} z ${all.length}.\n`
        + "Opublikowany arkusz zobaczą sędziowie z obsady, szkoleniowcy i administratorzy.";
      if (!window.confirm(message)) {
        event.preventDefault();
        return;
      }
    }
    submitting = true;
  });
})();
