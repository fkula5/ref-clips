// A list restored from the back/forward cache shows the read state it had when the user left it.
window.addEventListener("pageshow", (event) => {
  if (event.persisted) location.reload();
});
