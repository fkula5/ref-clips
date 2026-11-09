// Odtwarzacz: skróty klawiszowe, znaczniki „Zaznacz” (Z), początki kwart i znacznik z notatką (M).
(function () {
  const state = JSON.parse(document.getElementById("init-state").textContent);
  const video = document.getElementById("player");
  const wrap = document.getElementById("video-wrap");
  const $ = (id) => document.getElementById(id);
  const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
  const CAN_MARK = !!window.CAN_MARK;  // początki kwart
  const CAN_CLIP = !!window.CAN_CLIP;  // znaczniki (klipy)
  const DEBOUNCE_MS = 1000;            // jak na serwerze: podwójne kliknięcie
  const STATE_KEYS = ["marks", "periods", "missing_periods", "clips", "next_period"];
  let fps = state.fps || 25;
  let lastMarkAt = -Infinity;
  let highlightId = null;

  function clock(sec) {
    sec = Math.max(0, Math.round(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
  }

  function toast(text, isError) {
    const el = $("toast");
    el.textContent = text;
    el.classList.toggle("error", !!isError);
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3500);
  }

  // Krótki „błysk” na obrazie (widoczny także w pełnym ekranie, bo jest wewnątrz kontenera wideo).
  function flash(text, isError) {
    const el = $("flash");
    el.textContent = text;
    el.classList.toggle("error", !!isError);
    el.classList.remove("hidden");
    el.style.animation = "none";
    void el.offsetWidth;  // restart animacji
    el.style.animation = "";
    clearTimeout(flash.timer);
    flash.timer = setTimeout(() => el.classList.add("hidden"), 1300);
  }

  async function api(method, url, body) {
    const res = await fetch(url, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).detail; } catch (e) { /* brak JSON */ }
      const err = new Error(typeof detail === "string" && detail ? detail : `Błąd serwera (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  function applyState(res) {
    STATE_KEYS.forEach((key) => { if (key in res) state[key] = res[key]; });
  }

  function seek(t) {
    video.currentTime = Math.min(Math.max(0, t), video.duration || t);
  }

  function setSpeed(rate) {
    video.playbackRate = rate;
    $("speed").value = String(rate);
  }

  // --- render ---
  function renderPeriods() {
    const box = $("periods");
    box.replaceChildren();
    state.periods.forEach((p) => {
      const row = document.createElement("div");
      row.className = "period-row" + (p.period === state.next_period ? " next" : "");
      const chip = document.createElement("span");
      chip.className = "chip"; chip.textContent = p.period;
      row.appendChild(chip);
      const status = p.mark ? document.createElement("a") : document.createElement("span");
      if (p.mark) {
        status.href = "#"; status.textContent = p.mark.clock; status.title = "Przewiń do początku kwarty";
        status.addEventListener("click", (e) => { e.preventDefault(); seek(p.mark.time_sec); });
      } else {
        status.className = p.required ? "error-text" : "muted";
        status.textContent = p.required ? "brak" : "brak (opcjonalna)";
      }
      row.appendChild(status);
      if (state.single_period && p.mark) {
        const note = document.createElement("span");
        note.className = "muted small-note"; note.textContent = p.mark.time_sec === 0 ? "domyślnie 0:00" : "";
        row.appendChild(note);
      }
      if (CAN_MARK) {
        const set = document.createElement("button");
        set.type = "button"; set.className = "btn small";
        set.textContent = p.mark ? "Ustaw ponownie tutaj" : "Ustaw tutaj";
        set.addEventListener("click", () => addMark(p.period));
        row.appendChild(set);
        if (p.mark && !state.single_period) {
          const del = document.createElement("button");
          del.type = "button"; del.className = "btn small danger"; del.textContent = "×";
          del.title = "Usuń znacznik początku kwarty";
          del.addEventListener("click", () => deleteMark(p));
          row.appendChild(del);
        }
      }
      box.appendChild(row);
    });
    if ($("next-period")) $("next-period").textContent = state.next_period || "wszystkie ustawione";
  }

  const CUT_LABELS = { new: "w kolejce", queued: "w kolejce", cut: "wycięty", error: "błąd cięcia" };

  function renderMarkers() {
    const list = $("decisions");
    list.replaceChildren();
    state.clips.forEach((d) => {
      const li = document.createElement("li");
      if (d.id === highlightId) li.className = "new";
      const t = document.createElement("a");
      t.href = "#"; t.className = "t"; t.textContent = d.clock; t.title = "Przewiń do znacznika";
      t.addEventListener("click", (e) => { e.preventDefault(); seek(d.time_sec); });
      const where = document.createElement("span");
      where.textContent = d.period ? `${d.period} · ${d.period_clock}` : "kwarta nieustalona";
      where.title = d.period ? "Kwarta i czas od jej początku w czasie nagrania" : "Ustaw początki kwart";
      if (!d.period) where.className = "muted";
      li.append(t, " ", where);
      const meta = [d.official, d.category].filter(Boolean).join(" · ");
      if (meta) { const m = document.createElement("span"); m.className = "muted"; m.textContent = meta; li.append(" ", m); }
      const st = document.createElement("span");
      st.className = `badge ${d.status}`; st.textContent = CUT_LABELS[d.status] || d.status;
      if (d.error) st.title = d.error;
      const desc = document.createElement("span");
      desc.className = "chip" + (d.described ? "" : " warn"); desc.textContent = d.described ? "opisany" : "nieopisany";
      const link = document.createElement("a");
      link.href = `/clips/${d.id}`; link.className = "muted"; link.textContent = "klip";
      li.append(" ", st, " ", desc, " ", link);
      if (d.can_delete) {
        const del = document.createElement("button");
        del.type = "button"; del.className = "btn small danger"; del.textContent = "×";
        del.title = "Usuń znacznik (i plik klipu)";
        del.addEventListener("click", () => deleteMarker(d));
        li.append(" ", del);
      }
      list.appendChild(li);
    });
    if (!state.clips.length) {
      const empty = document.createElement("li");
      empty.className = "muted"; empty.textContent = CAN_CLIP ? "Brak znaczników — naciśnij Z, żeby dodać." : "Brak znaczników.";
      list.appendChild(empty);
    }
    $("dec-count").textContent = `(${state.clips.length})`;
    const undescribed = $("undescribed-count");  // przycisk „Opisz znaczniki (N)” w nagłówku
    if (undescribed) undescribed.textContent = String(state.clips.filter((c) => !c.described).length);
    $("mark-count").textContent = `Znaczniki: ${state.clips.length}`;
  }

  function renderBanner() {
    const missing = state.missing_periods || [];
    $("marks-banner").classList.toggle("hidden", !missing.length);
    $("missing-list").textContent = missing.join(", ");
  }

  function renderTimeline() {
    const bar = $("timeline");
    bar.replaceChildren();
    const dur = video.duration || state.duration;
    if (!dur) return;
    const add = (t, cls, title) => {
      const el = document.createElement("i");
      el.className = cls; el.style.left = `${(t / dur) * 100}%`; el.title = title;
      bar.appendChild(el);
    };
    state.marks.forEach((mk) => add(mk.time_sec, "tl-mark", `${mk.period} ${mk.clock}`));
    state.clips.forEach((d) => add(d.time_sec, "tl-dec", `${d.clock} ${d.official || ""}`));
  }

  function render() {
    renderPeriods();
    renderMarkers();
    renderBanner();
    renderTimeline();
  }

  // --- początki kwart ---
  async function addMark(period) {
    if (!CAN_MARK) return;
    period = period || state.next_period;
    if (!period) { toast("Wszystkie kwarty mają już znaczniki — użyj „Ustaw ponownie tutaj”.", true); return; }
    const t = video.currentTime;
    try {
      const res = await api("POST", `/api/videos/${state.video_id}/marks`, { time_sec: t, period });
      applyState(res);
      render();
      toast(`Początek ${res.period} ustawiony w ${clock(t)}`);
    } catch (err) { toast(err.message, true); }
  }

  async function deleteMark(p) {
    try {
      applyState(await api("DELETE", `/api/marks/${p.mark.id}`));
      render();
      toast(`Usunięto znacznik początku ${p.period}`);
    } catch (err) { toast(err.message, true); }
  }

  // --- znaczniki „Zaznacz” ---
  async function addMarker() {
    if (!CAN_CLIP) return;
    const now = performance.now();
    if (now - lastMarkAt < DEBOUNCE_MS) return;  // podwójne kliknięcie
    lastMarkAt = now;
    const t = video.currentTime;
    flash(`Znacznik ${clock(t)}`);  // natychmiast, przed odpowiedzią serwera
    try {
      const res = await api("POST", `/api/videos/${state.video_id}/markers`, { time_sec: t });
      applyState(res);
      highlightId = res.marker.id;
      render();
      if (res.created) flash(`Znacznik ${clock(res.marker.time_sec)} · razem ${state.clips.length}`);
      else toast("Pominięto — znacznik dodany przed chwilą");
    } catch (err) {
      lastMarkAt = -Infinity;
      flash("Nie zapisano znacznika", true);
      toast(err.message, true);
    }
  }

  async function undoMarker() {
    if (!CAN_CLIP) return;
    try {
      const res = await api("POST", `/api/videos/${state.video_id}/markers/undo`);
      applyState(res);
      render();
      flash(`Cofnięto znacznik ${clock(res.time_sec)}`);
    } catch (err) { toast(err.message, true); }
  }

  async function deleteMarker(d) {
    if (d.described && !confirm("Ten klip jest już opisany. Usunąć znacznik razem z klipem i jego opisem?")) return;
    try {
      applyState(await api("DELETE", `/api/clips/${d.id}${d.described ? "?confirm=true" : ""}`));
      render();
      toast(`Usunięto znacznik ${d.clock}`);
    } catch (err) { toast(err.message, true); }
  }

  // --- znacznik z notatką (M) ---
  function openQuick() {
    if (!$("quick-form")) return;
    video.pause();
    $("quick-form").classList.remove("hidden");
    $("quick-form").dataset.time = video.currentTime;
    $("quick-time").textContent = clock(video.currentTime);
    $("quick-text").value = "";
    $("quick-text").focus();
  }

  function closeQuick() {
    $("quick-form").classList.add("hidden");
    $("quick-text").blur();
  }

  if ($("quick-form")) $("quick-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const time = parseFloat($("quick-form").dataset.time);
    try {
      const res = await api("POST", `/api/videos/${state.video_id}/quick-clip`,
        { time_sec: time, text: $("quick-text").value });
      applyState(res);
      highlightId = res.clip.id;
      render();
      closeQuick();
      toast(res.warnings.length ? `Dodano (${res.warnings.join("; ")})` : `Dodano znacznik w ${clock(time)} — w kolejce do wycięcia`);
    } catch (err) { toast(err.message, true); }
  });

  // --- pełny ekran: kontener z wideo, żeby znaczniki i błysk były widoczne ---
  function toggleFullscreen() {
    const current = document.fullscreenElement || document.webkitFullscreenElement;
    if (current) { (document.exitFullscreen || document.webkitExitFullscreen).call(document); return; }
    const request = wrap.requestFullscreen || wrap.webkitRequestFullscreen;
    if (request) request.call(wrap);
    else toast("Ta przeglądarka nie obsługuje pełnego ekranu dla odtwarzacza", true);
  }

  function toggleHelp(show) {
    const help = $("help");
    help.classList.toggle("hidden", show === undefined ? !help.classList.contains("hidden") : !show);
  }

  function stepFrame(dir) {
    video.pause();
    const frame = Math.round(video.currentTime * fps);
    video.currentTime = (frame + dir) / fps + 0.0005;
  }

  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") {
      if (e.key === "Escape" && e.target.id === "quick-text") closeQuick();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    switch (e.key) {
      case " ": e.preventDefault(); if (video.paused) { video.play().catch(() => {}); } else { video.pause(); } break;
      case ",": case "<": e.preventDefault(); stepFrame(-1); break;
      case ".": case ">": e.preventDefault(); stepFrame(1); break;
      case "[": setSpeed(SPEEDS[Math.max(0, SPEEDS.indexOf(video.playbackRate) - 1)] ?? 1); break;
      case "]": setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, SPEEDS.indexOf(video.playbackRate) + 1)] ?? 1); break;
      case "z": case "Z": e.preventDefault(); if (!e.repeat) addMarker(); break;
      case "Backspace": e.preventDefault(); if (!e.repeat) undoMarker(); break;
      case "m": case "M": e.preventDefault(); openQuick(); break;
      case "q": case "Q": e.preventDefault(); if (!e.repeat) addMark(); break;
      case "f": case "F": e.preventDefault(); toggleFullscreen(); break;
      case "?": e.preventDefault(); toggleHelp(); break;
      case "Escape": toggleHelp(false); break;
    }
  });

  $("speed").addEventListener("change", (e) => { setSpeed(parseFloat(e.target.value)); e.target.blur(); });
  // Po kliknięciu przycisku fokus wraca do strony, żeby Spacja i Z nie „klikały” przycisku ponownie.
  document.addEventListener("click", (e) => {
    const button = e.target.closest && e.target.closest("button");
    if (button) button.blur();
  });
  if ($("btn-z")) $("btn-z").addEventListener("click", addMarker);
  if ($("btn-mark-fs")) $("btn-mark-fs").addEventListener("click", addMarker);
  if ($("btn-undo")) $("btn-undo").addEventListener("click", undoMarker);
  if ($("btn-m")) $("btn-m").addEventListener("click", openQuick);
  if ($("btn-q")) $("btn-q").addEventListener("click", () => addMark());
  $("btn-fs").addEventListener("click", toggleFullscreen);
  $("btn-help").addEventListener("click", () => toggleHelp());
  $("help-close").addEventListener("click", () => toggleHelp(false));
  $("timeline").addEventListener("click", (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    seek(((e.clientX - rect.left) / rect.width) * (video.duration || 0));
  });
  video.addEventListener("timeupdate", () => { $("clock").textContent = clock(video.currentTime); });
  video.addEventListener("loadedmetadata", () => {
    renderTimeline();
    if (window.START_AT) seek(window.START_AT);
  });
  // Spacja na fokusowanym <video> przełączałaby odtwarzanie dwa razy.
  video.addEventListener("keydown", (e) => { if (e.key === " ") e.preventDefault(); });

  // Stan cięcia klipów odświeża się sam, dopóki któryś czeka w kolejce.
  setInterval(async () => {
    if (document.hidden || !state.clips.some((c) => c.status === "new" || c.status === "queued")) return;
    try { applyState(await api("GET", `/api/videos/${state.video_id}/state`)); render(); } catch (err) { /* następna próba */ }
  }, 4000);

  render();
})();
