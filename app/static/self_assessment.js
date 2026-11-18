(() => {
  const form = document.getElementById("sa-form");
  if (!form) return;

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
    if (action === "submit"
        && !window.confirm("Wysłać samoocenę? Po wysłaniu nie będzie można jej edytować.")) {
      event.preventDefault();
      return;
    }
    submitting = true;
  });

  // Copies the clip's current description into the row's field; nothing is saved until the user saves.
  form.addEventListener("click", (event) => {
    const button = event.target.closest(".sa-insert");
    if (!button) return;
    const field = form.elements[button.dataset.target];
    if (field) {
      field.value = button.dataset.text;
      field.focus();
    }
  });
})();
