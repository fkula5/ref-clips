// Shared playback controls for every <video> in the app: a touch-sized strip (play, seek, frame step,
// speed, full screen) plus the keys `,` `.` `[` `]` `F`. Full screen goes to the wrapper, not to the bare
// <video>, so the strip and anything the page keeps in the wrapper (markers, toasts) stay usable.
// Videos opt in with `data-controls-strip` (optional `data-fps`); the match player calls attach() itself.
(function () {
  const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
  const IDLE_MS = 3000;
  const instances = [];
  let active = null;

  const fsElement = () => document.fullscreenElement || document.webkitFullscreenElement || null;

  function button(label, text, extraClass) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "btn pc-btn" + (extraClass ? " " + extraClass : "");
    el.setAttribute("aria-label", label);
    el.title = label;
    el.textContent = text;
    return el;
  }

  function attach(video, options) {
    if (video.dataset.pcReady) return null;
    video.dataset.pcReady = "1";
    const opts = options || {};
    const fps = opts.fps || parseFloat(video.dataset.fps) || 25;
    const canControl = opts.canControl || (() => true);
    const denied = opts.denied || (() => {});
    const allowed = () => canControl() || (denied(), false);

    let wrap = opts.wrap;
    if (!wrap) {
      wrap = document.createElement("div");
      video.replaceWith(wrap);
      wrap.appendChild(video);
    }
    wrap.classList.add("pc-wrap");
    // The native full screen would show the bare <video> without our strip; ours takes over.
    video.setAttribute("controlsList", "nofullscreen");

    const strip = document.createElement("div");
    strip.className = "pc-strip";
    strip.setAttribute("role", "group");
    strip.setAttribute("aria-label", "Sterowanie odtwarzaniem");

    const needsControl = [];
    const control = (el, handler) => {
      el.dataset.needsControl = "1";
      needsControl.push(el);
      el.addEventListener("click", () => { if (allowed()) handler(); });
      return el;
    };

    const playBtn = control(button("Odtwórz", "Odtwórz", "pc-play"), () => {
      if (video.paused) video.play().catch(() => {}); else video.pause();
    });
    const seekBy = (delta) => {
      video.currentTime = Math.min(Math.max(0, video.currentTime + delta), video.duration || Infinity);
    };
    const stepFrame = (dir) => {
      video.pause();
      const frame = Math.round(video.currentTime * fps);
      video.currentTime = Math.max(0, (frame + dir) / fps + 0.0005);
    };
    strip.append(playBtn);
    [["Wstecz o 5 sekund", "−5 s", -5], ["Wstecz o sekundę", "−1 s", -1]].forEach(([label, text, delta]) =>
      strip.append(control(button(label, text), () => seekBy(delta))));
    strip.append(control(button("Klatka wstecz", "−1 kl."), () => stepFrame(-1)));
    strip.append(control(button("Klatka naprzód", "+1 kl."), () => stepFrame(1)));
    [["Naprzód o sekundę", "+1 s", 1], ["Naprzód o 5 sekund", "+5 s", 5]].forEach(([label, text, delta]) =>
      strip.append(control(button(label, text), () => seekBy(delta))));

    const speedLabel = document.createElement("label");
    speedLabel.className = "pc-speed";
    speedLabel.append("Tempo ");
    const speed = document.createElement("select");
    if (opts.speedId) speed.id = opts.speedId;
    speed.className = "pc-select";
    SPEEDS.forEach((rate) => {
      const option = document.createElement("option");
      option.value = String(rate);
      option.textContent = `${rate}×`;
      speed.appendChild(option);
    });
    speed.value = String(video.playbackRate);
    speed.addEventListener("change", () => { setSpeed(parseFloat(speed.value)); speed.blur(); });
    speedLabel.appendChild(speed);
    strip.append(speedLabel);

    const fsBtn = button("Pełny ekran", "Pełny ekran", "pc-fs-btn");
    fsBtn.addEventListener("click", () => toggleFullscreen());
    strip.append(fsBtn);
    if (opts.extra && opts.extra.length) {
      const row = document.createElement("div");
      row.className = "pc-extra";
      opts.extra.forEach((el) => row.append(el));
      strip.append(row);
    }
    (opts.after || video).insertAdjacentElement("afterend", strip);

    function setSpeed(rate) {
      if (!allowed()) { speed.value = String(video.playbackRate); return; }
      video.playbackRate = rate;
    }

    // Safari on iPhone has no element full screen: fall back to a fixed, viewport-sized wrapper.
    function inFullscreen() { return fsElement() === wrap || wrap.classList.contains("pc-pseudo-fs"); }
    function pseudo(on) {
      wrap.classList.toggle("pc-pseudo-fs", on);
      document.documentElement.classList.toggle("pc-lock", on);
      syncFullscreen();
    }
    function toggleFullscreen() {
      if (inFullscreen()) {
        if (fsElement() === wrap) (document.exitFullscreen || document.webkitExitFullscreen).call(document);
        else pseudo(false);
        return;
      }
      const request = wrap.requestFullscreen || wrap.webkitRequestFullscreen;
      if (!request) { pseudo(true); return; }
      const result = request.call(wrap);
      if (result && result.catch) result.catch(() => pseudo(true));
    }

    let idleTimer = null;
    // Paused frames are analysed too, so the strip hides in both states. A focused control (an open
    // <select> keeps focus) keeps it up.
    function hideIfIdle() {
      if (strip.contains(document.activeElement)) { idleTimer = setTimeout(hideIfIdle, IDLE_MS); return; }
      wrap.classList.add("pc-idle");
    }
    function wake() {
      wrap.classList.remove("pc-idle");
      clearTimeout(idleTimer);
      if (inFullscreen()) idleTimer = setTimeout(hideIfIdle, IDLE_MS);
    }

    function syncFullscreen() {
      const on = inFullscreen();
      wrap.classList.toggle("is-fs", on);
      const label = on ? "Zamknij pełny ekran" : "Pełny ekran";
      fsBtn.textContent = label;
      fsBtn.title = label;
      fsBtn.setAttribute("aria-label", label);
      fsBtn.setAttribute("aria-pressed", on ? "true" : "false");
      wake();
      queueFit();
    }

    function sync() {
      const locked = !canControl();
      needsControl.forEach((el) => el.setAttribute("aria-disabled", locked ? "true" : "false"));
      strip.classList.toggle("is-locked", locked);
      const label = video.paused ? "Odtwórz" : "Pauza";
      playBtn.textContent = label;
      playBtn.title = label;
      playBtn.setAttribute("aria-label", label);
      if (document.activeElement !== speed) speed.value = String(video.playbackRate);
    }

    ["play", "pause", "ended", "ratechange"].forEach((name) => video.addEventListener(name, sync));
    video.addEventListener("play", () => { active = instance; });
    ["pointerdown", "focusin"].forEach((name) => wrap.addEventListener(name, () => { active = instance; }));
    ["pointermove", "pointerdown", "touchstart", "focusin"].forEach((name) =>
      wrap.addEventListener(name, wake, { passive: true }));
    // Fonts, wrapping and banners vary, so a CSS guess can push the strip below the fold.
    // Size the video from the real layout so the whole strip fits in the viewport.
    let fitQueued = false;
    function fit() {
      fitQueued = false;
      if (inFullscreen()) { video.style.maxHeight = ""; return; }
      const top = video.getBoundingClientRect().top + window.scrollY;
      const below = strip.getBoundingClientRect().bottom - video.getBoundingClientRect().bottom + 8;
      const max = Math.round(Math.min(window.innerHeight * 0.7, Math.max(220, window.innerHeight - top - below)));
      if (video.style.maxHeight !== max + "px") video.style.maxHeight = max + "px";
    }
    function queueFit() { if (!fitQueued) { fitQueued = true; requestAnimationFrame(fit); } }
    window.addEventListener("resize", queueFit);
    video.addEventListener("loadedmetadata", queueFit);
    if (window.ResizeObserver) new ResizeObserver(queueFit).observe(document.body);
    queueFit();

    syncFullscreen();
    sync();

    const instance = { video, wrap, strip, sync, syncFullscreen, toggleFullscreen, stepFrame, seekBy, setSpeed, allowed, pseudo, wake };
    instances.push(instance);
    if (!active) active = instance;
    return instance;
  }

  ["fullscreenchange", "webkitfullscreenchange"].forEach((name) =>
    document.addEventListener(name, () => instances.forEach((i) => i.syncFullscreen())));

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || event.target.isContentEditable) return;
    const open = instances.find((i) => i.wrap.classList.contains("pc-pseudo-fs"));
    if (event.key === "Escape" && open) { open.pseudo(false); return; }
    const target = active || instances[0];
    if (!target || !document.contains(target.video)) return;
    target.wake();
    switch (event.key) {
      case ",": case "<": event.preventDefault(); if (target.allowed()) target.stepFrame(-1); break;
      case ".": case ">": event.preventDefault(); if (target.allowed()) target.stepFrame(1); break;
      case "[": case "]": {
        event.preventDefault();
        const at = SPEEDS.indexOf(target.video.playbackRate);
        const next = event.key === "[" ? Math.max(0, at - 1) : Math.min(SPEEDS.length - 1, at + 1);
        target.setSpeed(SPEEDS[at < 0 ? SPEEDS.indexOf(1) : next]);
        break;
      }
      case "f": case "F": event.preventDefault(); target.toggleFullscreen(); break;
    }
  });

  function autoAttach() {
    document.querySelectorAll("video[data-controls-strip]").forEach((video) => attach(video));
  }
  document.addEventListener("htmx:afterSettle", autoAttach);
  autoAttach();

  window.PlayerControls = { attach, SPEEDS };
})();
