(function () {
  const form = document.getElementById("upload-form");
  if (!form || !window.tus) return;
  const matchId = form.dataset.match;
  const input = document.getElementById("upload-files");
  const list = document.getElementById("upload-files-list");
  const box = document.getElementById("upload-progress");
  const template = document.getElementById("content-template");
  const notesTemplate = document.getElementById("notes-template");
  const canNotes = form.dataset.canNotes === "1" && !!notesTemplate;
  const MAX_CHARS = parseInt(form.dataset.notesChars || "20000", 10);
  const MAX_LINES = parseInt(form.dataset.notesLines || "300", 10);
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const CHUNK = parseInt(form.dataset.chunkBytes || "", 10) || 50 * 1024 * 1024;  // smaller only in test mode (E2E)
  let busy = false, rows = [];

  const mb = (n) => (n / 1048576).toFixed(n >= 10485760 ? 0 : 1);

  function togglePeriods(row) {
    row.querySelector(".content-periods").hidden = row.querySelector(".content-kind").value !== "multi";
  }

  input.addEventListener("change", () => {
    list.innerHTML = "";
    rows = Array.from(input.files).map((file) => {
      const row = document.createElement("div");
      row.className = "file-row";
      const name = document.createElement("strong");
      name.textContent = file.name;  // text, not HTML
      row.append(name, " ", template.content.cloneNode(true));
      row.querySelector(".content-kind").addEventListener("change", () => togglePeriods(row));
      togglePeriods(row);
      if (canNotes) {
        row.appendChild(notesTemplate.content.cloneNode(true));
        row.querySelector(".notes-preview-btn").addEventListener("click", () => previewNotes(row));
      }
      list.appendChild(row);
      return { file, row };
    });
  });

  function notesOf(row) {
    const area = row.querySelector(".notes-text");
    return area ? area.value.replace(/\s+$/, "") : "";
  }

  function notesProblem(text) {
    if (text.length > MAX_CHARS) return "Notatki są za długie (maksymalnie " + MAX_CHARS + " znaków).";
    if (text && text.split("\n").length > MAX_LINES) return "Notatki mają za dużo linii (maksymalnie " + MAX_LINES + ").";
    return "";
  }

  async function previewNotes(row) {
    const box = row.querySelector(".notes-preview");
    const text = notesOf(row);
    box.textContent = "";
    const problem = notesProblem(text);
    if (problem) { box.textContent = problem; box.className = "notes-preview error-text"; return; }
    if (!text.trim()) { box.textContent = "Brak notatek."; box.className = "notes-preview muted"; return; }
    box.className = "notes-preview";
    try {
      const res = await fetch("/api/matches/" + matchId + "/notes/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ text: text }),
      });
      if (!res.ok) {
        let detail = "";
        try { detail = (await res.json()).detail; } catch (e) { /* not JSON */ }
        throw new Error(typeof detail === "string" && detail ? detail : "Błąd serwera (" + res.status + ")");
      }
      renderPreview(box, await res.json());
    } catch (err) {
      box.textContent = "Nie udało się zrobić podglądu: " + err.message;
      box.className = "notes-preview error-text";
    }
  }

  function renderPreview(box, rows) {
    const good = rows.filter((r) => r.ok).length;
    const summary = document.createElement("p");
    summary.className = "small-note";
    summary.textContent = good + " z " + rows.length + " linii zamieni się w klipy; linie bez czasu zostaną pominięte. " +
      "Klipy powstaną jako nieopisane — opis zatwierdzisz później.";
    const table = document.createElement("table");
    table.className = "preview";
    const head = table.createTHead().insertRow();
    ["Linia", "Czas", "Sędzia", "Kategoria", "Opis", "Uwagi"].forEach((h) => {
      const th = document.createElement("th"); th.textContent = h; head.appendChild(th);
    });
    const body = table.createTBody();
    rows.forEach((r) => {
      const tr = body.insertRow();
      tr.className = !r.ok ? "bad" : (r.warnings.length ? "warn" : "");
      [r.line_no, r.ok ? r.clock : "—", r.official || "—", r.category || "—", r.description, r.warnings.join("; ")]
        .forEach((value, i) => {
          const td = tr.insertCell();
          td.textContent = String(value);  // text, not HTML
          if (i === 5) td.className = "warn-text";
        });
    });
    box.replaceChildren(summary, table);
  }

  async function sendNotes(url, text, pct) {
    if (!text.trim()) return;
    try {
      const res = await fetch(url + "/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ text: text }),
      });
      if (!res.ok) {
        let detail = "";
        try { detail = (await res.json()).detail; } catch (e) { /* not JSON */ }
        throw new Error(typeof detail === "string" && detail ? detail : "błąd " + res.status);
      }
    } catch (err) {
      const warn = document.createElement("div");
      warn.className = "error-text small-note";
      warn.textContent = "Notatki nie zostały zapisane (" + err.message + "). Dodasz je po konwersji przyciskiem „Wklej notatki”.";
      pct.parentNode.appendChild(warn);
    }
  }

  function contentOf(row) {
    const kind = row.querySelector(".content-kind").value;
    if (kind !== "multi") return kind;
    const periods = Array.from(row.querySelectorAll(".content-periods input:checked")).map((c) => c.value);
    if (periods.length < 2) throw new Error("Dla kilku kwart zaznacz co najmniej dwie.");
    return periods.join(",");
  }

  function errorText(err) {
    const res = err.originalResponse;
    if (!res) return "Przerwano połączenie z serwerem. Wybierz plik i kliknij „Wgraj” ponownie — wgrywanie wznowi się od miejsca przerwania.";
    const status = res.getStatus();
    let detail = "";
    try { detail = JSON.parse(res.getBody()).detail; } catch (e) { /* not JSON */ }
    if (typeof detail !== "string") detail = "";
    if (status === 507) return "Brak miejsca na serwerze, spróbuj później.";
    if (status === 401) return "Sesja wygasła — zaloguj się ponownie i spróbuj jeszcze raz.";
    if (status === 403) return detail || "Brak uprawnień do wgrywania nagrań do tego meczu.";
    if (status === 413) return detail || "Plik jest za duży (limit " + form.dataset.maxGb + " GB).";
    return detail || "Błąd serwera (" + status + ").";
  }

  // Retry dropped connections and server errors, but not out-of-space or limit refusals.
  function shouldRetry(err) {
    const res = err.originalResponse;
    if (!res) return navigator.onLine !== false;
    const status = res.getStatus();
    if (status === 507 || status === 501) return false;
    if (status === 409) return err.originalRequest && err.originalRequest.getMethod() !== "POST";
    return status >= 500 || status === 423;
  }

  function uploadOne(file, content, label, notes) {
    return new Promise((resolve, reject) => {
      const row = document.createElement("div");
      row.className = "upload-row";
      const fname = document.createElement("span"); fname.className = "fname"; fname.textContent = file.name;
      const bar = document.createElement("progress"); bar.max = 100; bar.value = 0;
      const pct = document.createElement("span"); pct.className = "pct"; pct.textContent = "0%";
      const stop = document.createElement("button"); stop.type = "button"; stop.className = "btn small danger"; stop.textContent = "Przerwij";
      row.append(fname, bar, pct, stop);
      box.appendChild(row);

      let notesDone = Promise.resolve();
      const upload = new tus.Upload(file, {
        endpoint: "/uploads/",
        chunkSize: CHUNK,
        retryDelays: [0, 1000, 3000, 5000, 10000, 20000, 30000],
        headers: { "X-CSRF-Token": csrf },
        metadata: { filename: file.name, match_id: matchId, content: content, label: label },
        storeFingerprintForResuming: true,
        removeFingerprintOnSuccess: true,
        onShouldRetry: shouldRetry,
        onUploadUrlAvailable: () => { notesDone = sendNotes(upload.url, notes, pct); },
        onProgress: (sent, total) => {
          const p = Math.floor((sent / total) * 100);
          bar.value = p; pct.textContent = p + "% (" + mb(sent) + " / " + mb(total) + " MB)";
        },
        onSuccess: () => notesDone.then(() => { stop.remove(); pct.textContent = "gotowe — konwersja w tle"; resolve(); }),
        onError: (err) => {
          stop.remove();
          pct.textContent = errorText(err);
          pct.className = "pct error-text";
          const active = err.originalResponse && err.originalResponse.getHeader("X-Active-Upload");
          if (active) {
            const cancel = document.createElement("button");
            cancel.type = "button"; cancel.className = "btn small"; cancel.textContent = "Przerwij poprzednie wgrywanie";
            cancel.addEventListener("click", async () => {
              const r = await fetch(active, { method: "DELETE", headers: { "Tus-Resumable": "1.0.0", "X-CSRF-Token": csrf } });
              cancel.replaceWith(r.ok ? "Poprzednie wgrywanie przerwane — kliknij „Wgraj” ponownie." : "Nie udało się przerwać (" + r.status + ").");
            });
            row.appendChild(cancel);
          }
          reject(err);
        },
      });
      stop.addEventListener("click", () => {
        stop.disabled = true;
        upload.abort(true).then(() => { pct.textContent = "przerwano"; stop.remove(); reject(new Error("abort")); });
      });

      upload.findPreviousUploads().then((previous) => {
        const same = previous.find((p) => p.metadata && p.metadata.match_id === matchId);
        if (same) {
          upload.resumeFromPreviousUpload(same);
          pct.textContent = "wznawianie…";
          notesDone = sendNotes(upload.url, notes, pct);  // a resume does not create a session, so onUploadUrlAvailable is not called
        }
        upload.start();
      });
    });
  }

  window.addEventListener("beforeunload", (e) => {
    if (busy) { e.preventDefault(); e.returnValue = ""; }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!rows.length) return;
    let contents;
    try { contents = rows.map((r) => contentOf(r.row)); }
    catch (err) { alert(err.message); return; }
    const notes = rows.map((r) => notesOf(r.row));
    const problem = notes.map(notesProblem).find(Boolean);
    if (problem) { alert(problem); return; }
    const label = document.getElementById("upload-label").value.trim();
    const button = form.querySelector("button[type=submit]");
    button.disabled = true; busy = true;
    box.innerHTML = "";
    let failed = false;
    for (let i = 0; i < rows.length; i++) {
      const { file } = rows[i];
      try { await uploadOne(file, contents[i], rows.length > 1 && label ? label + " (" + file.name + ")" : label, notes[i]); }
      catch (err) { failed = true; if (err.message === "abort") break; }
    }
    busy = false; button.disabled = false;
    if (!failed) setTimeout(() => location.reload(), 800);
  });
})();
