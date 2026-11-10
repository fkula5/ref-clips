// "Oglądaj razem": a room where one person (the leader) drives playback and the others follow.
// Plugs into player.js only through window.RefPlayer (canControl, denied, refresh, api, toast).
(function () {
  const P = window.RefPlayer;
  if (!P) return;
  const video = P.video;
  const $ = (id) => document.getElementById(id);

  const HEARTBEAT_MS = 2000;
  const SEND_DELAY_MS = 80;       // coalesces play/seek/rate events of one gesture
  const CHECK_MS = 500;
  const DRIFT_PLAYING = 0.5;      // seconds
  const DRIFT_PAUSED = 0.015;     // frame steps of the leader arrive as paused seeks
  const COOLDOWN_MS = 1200;       // after a correction seek, let the video settle
  const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000];
  const FIRST_ATTEMPTS = 4;       // never connected at all: give up after this many tries
  const CLOSED = {
    4401: "Sesja wygasła. Zaloguj się ponownie.",
    4403: "Brak dostępu do tego nagrania.",
    4404: "Pokój został zamknięty (wygasł albo serwer się zrestartował). Utwórz nowy.",
    4409: "Ten pokój jest otwarty w innym oknie.",
    4410: "Pokój jest pełny.",
  };
  const CLOSED_OTHER = "Połączenie z pokojem zostało zerwane. Odśwież stronę.";

  let room = null, ws = null, me = null;
  let mode = "off";               // off | following | detached | leading
  let status = "connecting";      // connecting | online | offline | closed
  let closedText = "";
  let leader = null, people = [];
  let lead = null;                // {playing, t, rate, at}: the leader's last known state
  let welcomed = false, attempt = 0, cooldownUntil = 0;
  let reconnectTimer = null, sendTimer = null, markersTimer = null;

  P.canControl = () => mode !== "following";
  P.denied = () => P.toast(leader
    ? `Steruje: ${leader.name}. Użyj „Odłącz”, żeby oglądać samodzielnie.`
    : "Poczekaj na prowadzącego albo użyj „Odłącz”.", true);

  function send(message) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  }

  function sendState() {
    const t = video.currentTime;
    if (!Number.isFinite(t)) return;
    const playing = !video.paused && !video.ended;
    lead = { playing, t, rate: video.playbackRate, at: performance.now() };
    send({ type: "state", playing, t, rate: lead.rate });
  }

  function scheduleSend() {
    if (sendTimer) return;
    sendTimer = setTimeout(() => { sendTimer = null; if (mode === "leading") sendState(); }, SEND_DELAY_MS);
  }

  function tryPlay() {
    if (video.ended) return;
    video.play().then(() => showPlayGate(false)).catch((err) => {
      if (err && err.name === "NotAllowedError") showPlayGate(true);  // the browser wants a click first
    });
  }

  function showPlayGate(show) {
    $("watch-play").classList.toggle("hidden", !show);
  }

  // strict: a message or a viewer's own seek; otherwise the periodic check, which tolerates small drift.
  function applyLead(strict) {
    if (mode !== "following" || !lead) return;
    if (Math.abs(video.playbackRate - lead.rate) > 1e-6) {
      video.playbackRate = lead.rate;
      $("speed").value = String(lead.rate);
    }
    const now = performance.now();
    let want = lead.playing ? lead.t + ((now - lead.at) / 1000) * lead.rate : lead.t;
    if (video.duration) want = Math.min(want, video.duration);
    const tolerance = lead.playing || !strict ? DRIFT_PLAYING : DRIFT_PAUSED;
    if (Math.abs(video.currentTime - want) > tolerance && (strict || now >= cooldownUntil)) {
      video.currentTime = want;
      if (lead.playing) cooldownUntil = now + COOLDOWN_MS;
    }
    if (lead.playing && video.paused) tryPlay();
    else if (!lead.playing && !video.paused) video.pause();
  }

  function parseLead(s) {
    const t = Number(s && s.t), rate = Number(s && s.rate);
    if (!Number.isFinite(t) || !Number.isFinite(rate) || rate <= 0) return null;
    return { playing: !!s.playing, t, rate, at: performance.now() };
  }

  // Returns true when this viewer has just become the leader.
  function setRoster(msg) {
    leader = msg.leader || null;
    people = Array.isArray(msg.people) ? msg.people : [];
    const was = mode;
    if (leader && leader.id === me) mode = "leading";
    else if (mode === "leading") mode = "following";
    render();
    return mode === "leading" && was !== "leading";
  }

  function onMessage(raw) {
    let msg;
    try { msg = JSON.parse(raw); } catch (e) { return; }
    if (!msg || typeof msg !== "object") return;
    if (msg.type === "welcome") {
      me = msg.you;
      welcomed = true;
      attempt = 0;
      status = "online";
      setRoster(msg);
      if (mode === "leading") {
        sendState();  // this viewer's video is the truth for the room
      } else {
        lead = parseLead(msg.state) || lead;
        applyLead(true);
      }
    } else if (msg.type === "roster") {
      if (setRoster(msg)) sendState();
    } else if (msg.type === "state") {
      lead = parseLead(msg) || lead;
      applyLead(true);
    } else if (msg.type === "markers") {
      clearTimeout(markersTimer);
      markersTimer = setTimeout(() => P.refresh().catch(() => {}), 250);
    }
  }

  function connect() {
    clearTimeout(reconnectTimer);
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const sock = new WebSocket(`${scheme}://${location.host}/ws/watch/${encodeURIComponent(room)}`);
    ws = sock;
    sock.addEventListener("message", (e) => { if (ws === sock) onMessage(e.data); });
    sock.addEventListener("close", (e) => { if (ws === sock) onClose(e.code); });
  }

  function onClose(code) {
    ws = null;
    if (!room) return;
    if (code >= 4000 || code === 1009 || (!welcomed && attempt >= FIRST_ATTEMPTS)) {
      status = "closed";
      closedText = CLOSED[code] || (code ? CLOSED_OTHER : "Nie udało się połączyć z pokojem. Odśwież stronę albo zaloguj się ponownie.");
      leader = null; people = [];
      if (mode !== "detached") mode = "detached";
      render();
      return;
    }
    status = "offline";
    render();
    const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] * (0.75 + Math.random() * 0.5);
    attempt += 1;
    reconnectTimer = setTimeout(connect, delay);
  }

  function enter(id) {
    room = id;
    mode = "following";  // locked until the server says who leads
    status = "connecting";
    welcomed = false; attempt = 0; lead = null; leader = null; people = [];
    $("watch-link").value = `${location.origin}/watch/${id}`;
    history.replaceState(null, "", `${location.pathname}${location.search}#room=${id}`);
    connect();
    render();
  }

  function leave() {
    send({ type: "leave" });
    const sock = ws;
    ws = null;
    if (sock) sock.close(1000);
    clearTimeout(reconnectTimer);
    room = null; mode = "off"; lead = null; leader = null; people = [];
    showPlayGate(false);
    history.replaceState(null, "", location.pathname + location.search);
    render();
  }

  function text(tag, value, className) {
    const el = document.createElement(tag);
    el.textContent = value;
    if (className) el.className = className;
    return el;
  }

  function leaderLine() {
    if (status === "closed") return closedText;
    if (!welcomed) return "Łączenie z pokojem…";
    if (mode === "leading") return "Ty sterujesz";
    if (!leader) return "Czekamy na prowadzącego";
    const name = leader.away ? `${leader.name} (rozłączony)` : leader.name;
    return mode === "detached" ? `Oglądasz samodzielnie. Steruje: ${name}` : `Steruje: ${name}`;
  }

  function render() {
    const active = room !== null;
    $("btn-watch").classList.toggle("hidden", active);
    $("watch-panel").classList.toggle("hidden", !active);
    document.body.classList.toggle("watch-follow", mode === "following");
    $("speed").disabled = mode === "following";
    $("timeline").classList.toggle("locked", mode === "following");
    const badge = $("watch-badge");
    badge.classList.toggle("hidden", !active || status === "closed");
    if (!active) return;

    const line = leaderLine();
    $("watch-leader").textContent = line;
    badge.textContent = mode === "leading" ? "Sterujesz" : mode === "detached" ? "Oglądasz samodzielnie" : line;
    const state = $("watch-status");
    state.textContent = { online: "połączono", connecting: "łączę…", closed: "rozłączono",
                          offline: "połączenie przerwane, łączę ponownie…" }[status];
    state.className = "badge " + (status === "online" ? "ready" : status === "closed" ? "error" : "processing");

    const detach = $("watch-detach");
    detach.classList.toggle("hidden", mode === "leading" || status === "closed");
    detach.textContent = mode === "detached" ? "Dołącz z powrotem" : "Odłącz";

    const list = $("watch-people");
    list.replaceChildren();
    people.forEach((person) => {
      const li = document.createElement("li");
      li.append(text("span", person.name, "who-name"));
      if (person.id === me) li.append(text("span", "(Ty)", "muted"));
      if (leader && person.id === leader.id) li.append(text("span", "prowadzi", "badge ready"));
      if (mode === "leading" && person.id !== me) {
        const give = text("button", "Przekaż sterowanie", "btn small");
        give.type = "button";
        give.addEventListener("click", () => send({ type: "handover", to: person.id }));
        li.append(give);
      }
      list.appendChild(li);
    });
  }

  async function copyLink() {
    const input = $("watch-link");
    try {
      await navigator.clipboard.writeText(input.value);
      P.toast("Skopiowano link");
    } catch (e) {
      input.select();
      P.toast("Zaznaczono link. Skopiuj go skrótem Ctrl+C.");
    }
  }

  function onVideoEvent(kind) {
    if (mode === "leading") { scheduleSend(); return; }
    if (mode !== "following" || !lead) return;
    if (kind === "play" && !lead.playing) video.pause();
    else if (kind === "pause" && lead.playing) tryPlay();
    else applyLead(true);
  }

  ["play", "pause", "seeked"].forEach((kind) => video.addEventListener(kind, () => onVideoEvent(kind)));
  video.addEventListener("ratechange", () => onVideoEvent("ratechange"));
  video.addEventListener("seeking", () => { if (mode === "following") applyLead(true); });
  video.addEventListener("loadedmetadata", () => applyLead(true));
  video.addEventListener("playing", () => showPlayGate(false));

  setInterval(() => { if (mode === "leading") sendState(); }, HEARTBEAT_MS);
  setInterval(() => applyLead(false), CHECK_MS);

  $("btn-watch").addEventListener("click", async () => {
    try {
      enter((await P.api("POST", `/api/videos/${P.videoId}/watch`)).room);
    } catch (err) { P.toast(err.message, true); }
  });
  $("watch-copy").addEventListener("click", copyLink);
  $("watch-leave").addEventListener("click", leave);
  $("watch-play").addEventListener("click", () => applyLead(true));
  $("watch-detach").addEventListener("click", () => {
    if (mode === "following") mode = "detached";
    else if (mode === "detached" && status !== "closed") { mode = "following"; applyLead(true); }
    render();
  });

  const joined = /^#room=([\w-]{16,100})$/.exec(location.hash);
  if (joined) enter(joined[1]);
})();
