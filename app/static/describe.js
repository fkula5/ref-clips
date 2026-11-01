// Ekran opisywania: podgląd klipu, skróty klawiszowe (nie działają w polach tekstowych) i zapis z klawiatury.
(function () {
  const video = document.getElementById("preview");
  const form = document.getElementById("clip-form");
  const play = document.getElementById("btn-play");

  // Podgląd z wersji roboczej: tylko zakres klipu, zatrzymanie na jego końcu.
  if (video && video.dataset.end) {
    const start = parseFloat(video.dataset.start), end = parseFloat(video.dataset.end);
    const toStart = () => { video.currentTime = start; };
    video.addEventListener("loadedmetadata", toStart);
    if (video.readyState >= 1) toStart();
    video.addEventListener("timeupdate", () => {
      if (video.currentTime >= end) { video.pause(); video.currentTime = end; }
    });
    video.addEventListener("play", () => {
      if (video.currentTime >= end - 0.05 || video.currentTime < start) toStart();
    });
  }
  // Spacja na fokusowanym <video> przełączałaby odtwarzanie dwa razy.
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
  // Po kliknięciu przycisku fokus wraca do strony, żeby Spacja nie „klikała” go ponownie.
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
      // Ctrl+Enter w opisie, Enter w polu tekstowym lub liście kategorii zapisują formularz.
      if (form && e.key === "Enter" && !e.isComposing && (tag !== "textarea" || e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        form.requestSubmit();
      }
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (tag === "button" || tag === "a") return;  // Enter i Spacja działają tam jak zwykle
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
