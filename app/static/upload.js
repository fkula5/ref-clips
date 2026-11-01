// Wgrywanie wznawialne (tus): kawałki po 50 MB, ponawianie po zerwaniu połączenia,
// wznowienie po odświeżeniu strony (wybierz ten sam plik), pasek postępu i przerwanie.
(function () {
  const form = document.getElementById("upload-form");
  if (!form || !window.tus) return;
  const matchId = form.dataset.match;
  const input = document.getElementById("upload-files");
  const list = document.getElementById("upload-files-list");
  const box = document.getElementById("upload-progress");
  const template = document.getElementById("content-template");
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const CHUNK = 50 * 1024 * 1024;
  let busy = false, rows = [];

  const mb = (n) => (n / 1048576).toFixed(n >= 10485760 ? 0 : 1);

  // --- deklaracja zawartości każdego pliku ---------------------------------------
  function togglePeriods(row) {
    row.querySelector(".content-periods").hidden = row.querySelector(".content-kind").value !== "multi";
  }

  input.addEventListener("change", () => {
    list.innerHTML = "";
    rows = Array.from(input.files).map((file) => {
      const row = document.createElement("div");
      row.className = "file-row";
      const name = document.createElement("strong");
      name.textContent = file.name;  // tekst, nie HTML
      row.append(name, " ", template.content.cloneNode(true));
      row.querySelector(".content-kind").addEventListener("change", () => togglePeriods(row));
      togglePeriods(row);
      list.appendChild(row);
      return { file, row };
    });
  });

  function contentOf(row) {
    const kind = row.querySelector(".content-kind").value;
    if (kind !== "multi") return kind;
    const periods = Array.from(row.querySelectorAll(".content-periods input:checked")).map((c) => c.value);
    if (periods.length < 2) throw new Error("Dla kilku kwart zaznacz co najmniej dwie.");
    return periods.join(",");
  }

  // --- błędy ----------------------------------------------------------------------
  function errorText(err) {
    const res = err.originalResponse;
    if (!res) return "Przerwano połączenie z serwerem. Wybierz plik i kliknij „Wgraj” ponownie — wgrywanie wznowi się od miejsca przerwania.";
    const status = res.getStatus();
    let detail = "";
    try { detail = JSON.parse(res.getBody()).detail; } catch (e) { /* brak JSON */ }
    if (typeof detail !== "string") detail = "";
    if (status === 507) return "Brak miejsca na serwerze, spróbuj później.";
    if (status === 401) return "Sesja wygasła — zaloguj się ponownie i spróbuj jeszcze raz.";
    if (status === 403) return detail || "Brak uprawnień do wgrywania nagrań do tego meczu.";
    if (status === 413) return detail || "Plik jest za duży (limit " + form.dataset.maxGb + " GB).";
    return detail || "Błąd serwera (" + status + ").";
  }

  // Ponawiamy zerwane połączenia i błędy serwera, ale nie brak miejsca ani odmowę limitu.
  function shouldRetry(err) {
    const res = err.originalResponse;
    if (!res) return navigator.onLine !== false;
    const status = res.getStatus();
    if (status === 507 || status === 501) return false;
    if (status === 409) return err.originalRequest && err.originalRequest.getMethod() !== "POST";
    return status >= 500 || status === 423;
  }

  // --- jeden plik -----------------------------------------------------------------
  function uploadOne(file, content, label) {
    return new Promise((resolve, reject) => {
      const row = document.createElement("div");
      row.className = "upload-row";
      const fname = document.createElement("span"); fname.className = "fname"; fname.textContent = file.name;
      const bar = document.createElement("progress"); bar.max = 100; bar.value = 0;
      const pct = document.createElement("span"); pct.className = "pct"; pct.textContent = "0%";
      const stop = document.createElement("button"); stop.type = "button"; stop.className = "btn small danger"; stop.textContent = "Przerwij";
      row.append(fname, bar, pct, stop);
      box.appendChild(row);

      const upload = new tus.Upload(file, {
        endpoint: "/uploads/",
        chunkSize: CHUNK,
        retryDelays: [0, 1000, 3000, 5000, 10000, 20000, 30000],
        headers: { "X-CSRF-Token": csrf },
        metadata: { filename: file.name, match_id: matchId, content: content, label: label },
        storeFingerprintForResuming: true,
        removeFingerprintOnSuccess: true,
        onShouldRetry: shouldRetry,
        onProgress: (sent, total) => {
          const p = Math.floor((sent / total) * 100);
          bar.value = p; pct.textContent = p + "% (" + mb(sent) + " / " + mb(total) + " MB)";
        },
        onSuccess: () => { stop.remove(); pct.textContent = "gotowe — konwersja w tle"; resolve(); },
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

      // Wznowienie po odświeżeniu strony: ten sam plik i mecz => dalej od miejsca przerwania.
      upload.findPreviousUploads().then((previous) => {
        const same = previous.find((p) => p.metadata && p.metadata.match_id === matchId);
        if (same) { upload.resumeFromPreviousUpload(same); pct.textContent = "wznawianie…"; }
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
    const label = document.getElementById("upload-label").value.trim();
    const button = form.querySelector("button[type=submit]");
    button.disabled = true; busy = true;
    box.innerHTML = "";
    let failed = false;
    for (let i = 0; i < rows.length; i++) {
      const { file } = rows[i];
      try { await uploadOne(file, contents[i], rows.length > 1 && label ? label + " (" + file.name + ")" : label); }
      catch (err) { failed = true; if (err.message === "abort") break; }
    }
    busy = false; button.disabled = false;
    if (!failed) setTimeout(() => location.reload(), 800);
  });
})();
