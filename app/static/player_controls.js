// One Video.js control bar for every <video> in the app, plus the keys `,` `.` `[` `]` `F`.
// Videos opt in with `data-controls-strip` (optional `data-fps`); the match player calls attach() itself.
// Full screen goes to the Video.js player element, so everything moved into it (markers, flash, toast)
// stays visible. Video.js's own hotkeys stay off: the page and this file own the keyboard.
(function () {
  const videojs = window.videojs;
  const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
  const IDLE_MS = 3000;
  const instances = [];
  let active = null;

  window.VIDEOJS_NO_DYNAMIC_STYLE = true;
  videojs.addLanguage("pl", {
    "Pause": "Pauza",
    "Exit Fullscreen": "Zamknij pełny ekran",
    "Playback Rate": "Tempo",
  });

  // Video.js swallows every other key pressed on a focused control; the page's shortcuts must still work there.
  videojs.getComponent("Component").prototype.handleKeyDown = function () {};

  // A text button for the control bar: the label is visible, the full name is the accessible one.
  class PcButton extends videojs.getComponent("Button") {
    constructor(player, options) {
      super(player, options);
      this.addClass("pc-ctl");
      if (options.className) this.addClass(options.className);
      this.el().setAttribute("aria-label", options.label);
      this.el().querySelector(".vjs-icon-placeholder").textContent = options.text;
    }
    buildCSSClass() { return "pc-btn-vjs " + super.buildCSSClass(); }
    handleClick() { this.options_.onClick(); }
  }
  videojs.registerComponent("PcButton", PcButton);

  // Anything that drives playback; a watch-together follower may not touch it.
  const DRIVERS = ".vjs-play-control, .vjs-progress-control, .vjs-playback-rate, .pc-ctl";

  function attach(video, options) {
    if (video.dataset.pcReady) return null;
    video.dataset.pcReady = "1";
    const opts = options || {};
    const fps = opts.fps || parseFloat(video.dataset.fps) || 25;
    const canControl = opts.canControl || (() => true);
    const denied = opts.denied || (() => {});
    const allowed = () => canControl() || (denied(), false);

    // Video.js reuses a parent marked data-vjs-player as its element; without it the iPhone gets a
    // cloned <video> and every other script would hold a dead reference.
    const box = document.createElement("div");
    box.dataset.vjsPlayer = "";
    video.replaceWith(box);
    box.appendChild(video);
    // Video.js copies the tag's id to its element and renames the tag; the page keeps the id on the <video>.
    const videoId = video.id;
    video.removeAttribute("id");
    video.classList.add("video-js");

    const step = (name, label, text, onClick, className) =>
      ({ name, componentClass: "PcButton", controlText: label, label, text, onClick, className });
    const seekBy = (delta) => {
      video.currentTime = Math.min(Math.max(0, video.currentTime + delta), video.duration || Infinity);
    };
    const stepFrame = (dir) => {
      video.pause();
      const frame = Math.round(video.currentTime * fps);
      video.currentTime = Math.max(0, (frame + dir) / fps + 0.0005);
    };

    const player = videojs(video, {
      language: "pl",
      controls: true,
      preload: video.getAttribute("preload") || "auto",
      playsinline: true,
      preferFullWindow: true,
      inactivityTimeout: IDLE_MS,
      playbackRates: SPEEDS,
      userActions: {
        hotkeys: false,
        doubleClick: false,
        click: () => { if (allowed()) { if (video.paused) video.play().catch(() => {}); else video.pause(); } },
      },
      children: ["mediaLoader", "controlBar", "errorDisplay"],
      controlBar: {
        children: [
          "playToggle",
          step("pcBack5", "Wstecz o 5 sekund", "−5 s", () => seekBy(-5)),
          step("pcBack1", "Wstecz o sekundę", "−1 s", () => seekBy(-1), "pc-minor"),
          step("pcFrameBack", "Klatka wstecz", "−1 kl.", () => stepFrame(-1)),
          step("pcFrameFwd", "Klatka naprzód", "+1 kl.", () => stepFrame(1)),
          step("pcFwd1", "Naprzód o sekundę", "+1 s", () => seekBy(1), "pc-minor"),
          step("pcFwd5", "Naprzód o 5 sekund", "+5 s", () => seekBy(5)),
          "volumePanel",
          "currentTimeDisplay", "timeDivider", "durationDisplay",
          "progressControl",
          "playbackRateMenuButton",
          "fullscreenToggle",
        ],
        volumePanel: { inline: true },
      },
    });
    const el = player.el();
    const bar = player.getChild("controlBar").el();
    video.id = videoId;
    video.removeAttribute("controls");
    el.classList.add("pc-player");
    (opts.overlays || []).forEach((node) => el.appendChild(node));

    // A follower's taps on the playback controls only explain who leads. Captured at the player so
    // Video.js's own handlers on the controls never run.
    ["click", "mousedown", "pointerdown", "touchstart", "keydown"].forEach((type) => el.addEventListener(type, (event) => {
      if (canControl()) return;
      const target = event.target.closest && event.target.closest(DRIVERS);
      if (!target || !el.contains(target)) return;
      if (event.type === "keydown" && ["Tab", "Shift", "Escape"].includes(event.key)) return;
      event.stopImmediatePropagation();
      if (event.type === "click" || event.type === "keydown") { event.preventDefault(); denied(); }
    }, true));

    function setSpeed(rate) {
      if (!allowed()) return;
      video.playbackRate = rate;
    }

    // iPhone has no element full screen: the full-window fallback locks the page scroll and leaves the page
    // scrolled elsewhere on exit, so the position is taken before entering and restored afterwards.
    let pageY = null;
    const rememberScroll = () => { if (!player.isFullscreen()) pageY = window.scrollY; };
    bar.addEventListener("pointerdown", rememberScroll, { capture: true, passive: true });

    function toggleFullscreen() {
      if (player.isFullscreen()) { player.exitFullscreen(); return; }
      rememberScroll();
      const request = player.requestFullscreen();
      if (request && request.catch) request.catch(() => player.enterFullWindow());
    }

    // The marker bar and the extra buttons live in the page until full screen, where the page is out of reach.
    const moved = [];
    function relocate(node, into, before) {
      if (!node) return;
      const mark = document.createComment("");
      node.replaceWith(mark);
      moved.push({ node, mark });
      into.insertBefore(node, before || null);
    }
    function onFullscreen() {
      const on = player.isFullscreen();
      if (on) {
        (opts.fsOverlays || []).forEach((node) => relocate(node, el));
        (opts.fsButtons || []).forEach((node) => relocate(node, bar, bar.querySelector(".vjs-playback-rate")));
      } else {
        moved.splice(0).forEach(({ node, mark }) => mark.replaceWith(node));
        if (pageY !== null) {
          const y = pageY;
          pageY = null;
          requestAnimationFrame(() => window.scrollTo(0, y));
        }
      }
      el.classList.toggle("pc-fs-moved", on && !!(opts.fsOverlays && opts.fsOverlays.length));
      wake();
      fit();
    }
    player.on("fullscreenchange", onFullscreen);

    // Video.js only starts watching for activity at the first play (pinned 8.24.1, so the private method is stable);
    // the bar has to hide while paused as well, and the video is paused when the page opens.
    const watchActivity = player.listenForUserActivity_.bind(player);
    player.listenForUserActivity_ = () => {};
    watchActivity();
    // Paused frames are analysed too, so the bar hides in both states. It stays up until the first interaction,
    // while a control has keyboard focus and while a menu is open.
    let touched = false;
    ["pointermove", "pointerdown", "touchstart", "keydown", "focusin"].forEach((name) =>
      el.addEventListener(name, () => { touched = true; }, { capture: true, passive: true }));
    player.on("userinactive", () => {
      const focused = bar.contains(document.activeElement) && document.activeElement.matches(":focus-visible");
      if (touched && !focused && !bar.querySelector(".vjs-lock-showing")) return;
      player.userActive(true);
      if (touched) setTimeout(() => player.reportUserActivity(), IDLE_MS);
    });
    function wake() { touched = true; player.reportUserActivity(); }

    function sync() {
      const locked = !canControl();
      el.classList.toggle("pc-locked", locked);
      el.querySelectorAll(DRIVERS).forEach((node) => node.setAttribute("aria-disabled", locked ? "true" : "false"));
    }

    ["pointerdown", "focusin"].forEach((name) => el.addEventListener(name, () => { active = instance; }));
    video.addEventListener("play", () => { active = instance; });

    // Fonts, wrapping and banners vary, so a CSS guess can push the page below the fold. Size the
    // player from the real layout so it, and whatever `opts.keep` points at, fit in the viewport.
    let fitQueued = false;
    function fit() {
      fitQueued = false;
      if (player.isFullscreen()) { el.style.maxHeight = ""; return; }
      const rect = el.getBoundingClientRect();
      const top = rect.top + window.scrollY;
      const below = (opts.keep ? opts.keep.getBoundingClientRect().bottom - rect.bottom : 0) + 8;
      const max = Math.round(Math.min(window.innerHeight * 0.7, Math.max(220, window.innerHeight - top - below)));
      if (el.style.maxHeight !== max + "px") el.style.maxHeight = max + "px";
    }
    function queueFit() { if (!fitQueued) { fitQueued = true; requestAnimationFrame(fit); } }
    function ratio() {
      if (video.videoWidth) el.style.setProperty("--pc-ar", `${video.videoWidth} / ${video.videoHeight}`);
      queueFit();
    }
    window.addEventListener("resize", queueFit);
    video.addEventListener("loadedmetadata", ratio);
    if (window.ResizeObserver) new ResizeObserver(queueFit).observe(document.body);
    ratio();

    sync();
    const instance = { video, player, el, sync, toggleFullscreen, stepFrame, seekBy, setSpeed, allowed, wake };
    instances.push(instance);
    if (!active) active = instance;
    return instance;
  }

  function prune() {
    instances.filter((i) => !document.contains(i.el)).forEach((gone) => {
      instances.splice(instances.indexOf(gone), 1);
      if (active === gone) active = null;
      try { gone.player.dispose(); } catch (e) { /* already gone with its DOM */ }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || event.target.isContentEditable) return;
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
    prune();
    document.querySelectorAll("video[data-controls-strip]").forEach((video) => attach(video));
  }
  document.addEventListener("htmx:afterSettle", autoAttach);
  autoAttach();

  window.PlayerControls = { attach, SPEEDS };
})();
