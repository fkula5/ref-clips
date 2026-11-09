// Strzałki w każdym odtwarzaczu: ←/→ ±1 s, z Shift ±5 s.
// Pasek przeglądarki kliknięty myszą dostaje fokus i przejmuje strzałki (skok o 1% długości filmu, bez Shift),
// a klawisze w ogóle nie docierają wtedy do strony — dlatego zabieramy mu fokus. Fokus z klawiatury (Tab) zostaje.
document.addEventListener("focusin", (e) => {
  if (e.target.tagName === "VIDEO" && !e.target.matches(":focus-visible")) e.target.blur();
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return;
  const video = document.querySelector("video");
  if (!video) return;
  e.preventDefault();
  e.stopPropagation();
  const step = (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 5 : 1);
  video.currentTime = Math.min(Math.max(0, video.currentTime + step), video.duration || Infinity);
}, true);
