// Arrow keys in every player: left/right +-1 s, with Shift +-5 s.
// The browser's slider, once clicked with the mouse, takes focus and the arrow keys (a jump of 1% of
// the movie, no Shift), and the keys then do not reach the page at all, so we take focus away from it.
// Keyboard focus (Tab) stays.
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
