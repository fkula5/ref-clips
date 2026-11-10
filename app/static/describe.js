(function () {
  const video = document.getElementById("preview");
  const form = document.getElementById("clip-form");
  const play = document.getElementById("btn-play");

  if (video && video.dataset.end) {
    const start = parseFloat(video.dataset.start), end = parseFloat(video.dataset.end);
    const toStart = () => { video.currentTime = start; };
    video.addEventListener("loadedmetadata", toStart);
    if (video.readyState >= 1) toStart();
    video.addEventListener("timeupdate", () => {
      // A late event from the previous item (during seeking) must not stop the new playback.
      if (!video.seeking && !video.paused && video.currentTime >= end) video.pause();
    });
    video.addEventListener("play", () => {
      if (video.currentTime >= end - 0.05 || video.currentTime < start) toStart();
    });
  }
  // Space on a focused <video> would toggle playback twice.
  if (video) video.addEventListener("keydown", (e) => { if (e.key === " ") e.preventDefault(); });

  function togglePlay() {
    if (!video) return;
    if (video.paused) { video.play().catch(() => {}); } else { video.pause(); }
  }
  function restart() {
    if (!video) return;
    video.currentTime = video.dataset.start ? parseFloat(video.dataset.start) : 0;
    video.play().catch(() => {});
  }
  if (play) play.addEventListener("click", togglePlay);
  // After a button click focus returns to the page, so Space does not "click" it again.
  document.addEventListener("click", (e) => {
    const button = e.target.closest && e.target.closest("button");
    if (button && button.type === "button") button.blur();
  });

  function pickOfficial(key) {
    if (!form) return;
    const radio = form.querySelector(`input[name=official][data-key="${key}"]`);
    if (radio) radio.checked = true;
  }

  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    const typing = tag === "input" && !["radio", "checkbox", "button", "submit"].includes(e.target.type);
    if (typing || tag === "textarea" || tag === "select") {
      if (form && e.key === "Enter" && !e.isComposing && (tag !== "textarea" || e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        form.requestSubmit();
      }
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (tag === "button" || tag === "a") return;
    if (e.key === "Enter" && form && tag !== "video") {
      e.preventDefault();
      form.requestSubmit();
      return;
    }
    switch (e.key) {
      case "1": case "2": case "3": case "0": e.preventDefault(); pickOfficial(e.key); break;
      case " ": e.preventDefault(); togglePlay(); break;
      case "k": case "K": e.preventDefault(); { const s = document.getElementById("category-select"); if (s) s.focus(); } break;
      case "d": case "D": e.preventDefault(); { const d = document.getElementById("description"); if (d) d.focus(); } break;
      case "r": case "R": e.preventDefault(); restart(); break;
    }
  });
})();
