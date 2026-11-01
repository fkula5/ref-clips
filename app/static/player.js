// Odtwarzacz z skrótami klawiszowymi, znacznikami kwart i szybkim dodawaniem klipów.
(function () {
  const state = JSON.parse(document.getElementById("init-state").textContent);
  const video = document.getElementById("player");
  const $ = (id) => document.getElementById(id);
  const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
  let fps = state.fps || 25;

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

  async function api(method, url, body) {
    const res = await fetch(url, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json();
  }

  function seek(t) {
    video.currentTime = Math.min(Math.max(0, t), video.duration || t);
  }

  function setSpeed(rate) {
    video.playbackRate = rate;
    $("speed").value = String(rate);
  }

  // --- render listy znaczników i decyzji ---
  function render() {
    const marks = $("marks");
    marks.innerHTML = "";
    state.marks.forEach((mk) => {
      const row = document.createElement("div");
      row.className = "row mark";
      row.innerHTML = `<a href="#" class="chip">${mk.period}</a><a href="#">${mk.clock}</a>`;
      row.querySelectorAll("a").forEach((a) =>
        a.addEventListener("click", (e) => { e.preventDefault(); seek(mk.time_sec); }));
      if (window.CAN_MARK) {
        const del = document.createElement("button");
        del.className = "btn small danger"; del.type = "button"; del.textContent = "×";
        del.addEventListener("click", async () => {
          Object.assign(state, await api("DELETE", `/api/marks/${mk.id}`));
          render();
        });
        row.appendChild(del);
      }
      marks.appendChild(row);
    });
    if (!state.marks.length) marks.innerHTML = '<p class="muted">Brak znaczników kwart.</p>';
    if ($("next-period")) $("next-period").textContent = state.next_period;
    if ($("mark-period")) $("mark-period").value = state.next_period;

    const list = $("decisions");
    list.innerHTML = "";
    state.clips.forEach((d) => {
      const li = document.createElement("li");
      const meta = [d.period, d.official, d.category].filter(Boolean).join(" · ");
      li.innerHTML = `<a href="#" class="t">${d.clock}</a> <span></span>
        <a class="muted" href="/clips/${d.id}">klip (${d.status === "cut" ? "gotowy" : "w kolejce"})</a>`;
      li.querySelector("span").textContent = meta || "—";  // tekst, nie HTML
      li.querySelector(".t").addEventListener("click", (e) => { e.preventDefault(); seek(d.time_sec); });
      list.appendChild(li);
    });
    $("dec-count").textContent = `(${state.clips.length})`;
    renderTimeline();
  }

  function renderTimeline() {
    const bar = $("timeline");
    bar.innerHTML = "";
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

  // --- akcje ---
  async function addMark(period) {
    const t = video.currentTime;
    try {
      const res = await api("POST", `/api/videos/${state.video_id}/marks`, { time_sec: t, period });
      Object.assign(state, res);
      render();
      toast(`Znacznik ${res.period} w ${clock(t)}`);
    } catch (err) { toast("Nie udało się zapisać znacznika", true); }
  }

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
      Object.assign(state, { clips: res.clips, marks: res.marks, next_period: res.next_period });
      render();
      closeQuick();
      toast(res.warnings.length ? `Dodano (${res.warnings.join("; ")})` : `Dodano klip w ${clock(time)} — w kolejce do wycięcia`);
    } catch (err) { toast("Nie udało się dodać klipu", true); }
  });

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
    const big = e.shiftKey ? 5 : 1;
    switch (e.key) {
      case " ": e.preventDefault(); video.paused ? video.play() : video.pause(); break;
      case "ArrowLeft": e.preventDefault(); seek(video.currentTime - big); break;
      case "ArrowRight": e.preventDefault(); seek(video.currentTime + big); break;
      case ",": case "<": e.preventDefault(); stepFrame(-1); break;
      case ".": case ">": e.preventDefault(); stepFrame(1); break;
      case "[": setSpeed(SPEEDS[Math.max(0, SPEEDS.indexOf(video.playbackRate) - 1)] ?? 1); break;
      case "]": setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, SPEEDS.indexOf(video.playbackRate) + 1)] ?? 1); break;
      case "m": case "M": e.preventDefault(); openQuick(); break;
      case "q": case "Q": e.preventDefault(); if (window.CAN_MARK) addMark(); break;
    }
  });

  $("speed").addEventListener("change", (e) => setSpeed(parseFloat(e.target.value)));
  if ($("btn-m")) $("btn-m").addEventListener("click", openQuick);
  if ($("btn-q")) $("btn-q").addEventListener("click", () => addMark());
  if ($("btn-mark")) $("btn-mark").addEventListener("click", () => addMark($("mark-period").value));
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

  render();
})();
