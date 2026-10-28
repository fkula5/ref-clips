// Strona klipu: korekta początku/końca, komentarze przypięte do sekundy, odpowiedzi.
function clipVideo() { return document.getElementById("clip-video"); }

function seekClip(sec) {
  const v = clipVideo();
  if (v) { v.currentTime = sec; v.play(); }
}

function replyTo(id) {
  document.getElementById("parent_id").value = id;
  document.getElementById("reply-label").textContent = "(odpowiedź na komentarz)";
  document.querySelector("#comments-box textarea").focus();
}

function clearCommentForm() {
  document.getElementById("at_sec").value = "";
  document.getElementById("parent_id").value = "";
  document.getElementById("pin-label").textContent = "";
  document.getElementById("reply-label").textContent = "";
}

(function () {
  const pin = document.getElementById("pin-btn");
  if (pin) pin.addEventListener("click", () => {
    const v = clipVideo();
    const t = v ? v.currentTime : 0;
    document.getElementById("at_sec").value = t.toFixed(2);
    document.getElementById("pin-label").textContent = `przypięto do ${t.toFixed(1)} s`;
  });

  // przyciski ±1 s przy polach początku/końca klipu
  function toSeconds(text) {
    text = text.trim().replace(",", ".");
    const parts = text.split(/[:]/).map(Number);
    if (parts.some(isNaN)) return NaN;
    return parts.reduce((acc, p) => acc * 60 + p, 0);
  }
  function fmt(sec) {
    sec = Math.max(0, Math.round(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
  }
  document.querySelectorAll("[data-shift]").forEach((btn) => btn.addEventListener("click", () => {
    const input = document.getElementById(btn.dataset.shift === "start" ? "adj-start" : "adj-end");
    const v = toSeconds(input.value);
    if (!isNaN(v)) input.value = fmt(v + Number(btn.dataset.by));
  }));
})();
