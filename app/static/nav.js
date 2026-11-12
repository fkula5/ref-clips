// Marks the page as script-enabled right away (this script sits in <head>), so the narrow-screen menu
// collapses only when it can be reopened. Without JS the links simply stay visible.
document.documentElement.classList.add("js");

document.addEventListener("DOMContentLoaded", () => {
  const header = document.querySelector("header.top");
  const button = header && header.querySelector(".nav-toggle");
  if (!button) return;

  const set = (open) => {
    header.classList.toggle("menu-open", open);
    button.setAttribute("aria-expanded", String(open));
  };
  const isOpen = () => button.getAttribute("aria-expanded") === "true";

  button.addEventListener("click", () => set(!isOpen()));
  header.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !isOpen()) return;
    // Focus would be lost when the focused link disappears with the panel.
    if (header.contains(document.activeElement)) button.focus();
    set(false);
  });
  header.addEventListener("click", (event) => {
    if (event.target.closest("#site-nav a")) set(false);
  });
  document.addEventListener("click", (event) => {
    if (isOpen() && !header.contains(event.target)) set(false);
  });
  // Back/forward cache restores the page as it was left, with the panel open.
  window.addEventListener("pageshow", (event) => { if (event.persisted) set(false); });
});
