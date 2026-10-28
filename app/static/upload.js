// Wgrywanie dużych plików: surowe body przez XHR (strumieniowo po stronie serwera) + pasek postępu.
(function () {
  const form = document.getElementById("upload-form");
  if (!form) return;
  const box = document.getElementById("upload-progress");

  function uploadOne(file, matchId, label, source) {
    return new Promise((resolve, reject) => {
      const row = document.createElement("div");
      row.className = "upload-row";
      row.innerHTML = `<span>${file.name}</span> <progress max="100" value="0"></progress> <span class="pct">0%</span>`;
      box.appendChild(row);
      const bar = row.querySelector("progress"), pct = row.querySelector(".pct");

      const xhr = new XMLHttpRequest();
      const qs = new URLSearchParams({ filename: file.name, label, source });
      xhr.open("POST", `/matches/${matchId}/upload?${qs}`);
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        const p = Math.round((e.loaded / e.total) * 100);
        bar.value = p; pct.textContent = `${p}%`;
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) { pct.textContent = "gotowe — konwersja w tle"; resolve(); }
        else { pct.textContent = `błąd ${xhr.status}: ${xhr.responseText}`; reject(new Error(xhr.responseText)); }
      };
      xhr.onerror = () => { pct.textContent = "błąd połączenia"; reject(new Error("network")); };
      xhr.send(file);
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const files = Array.from(document.getElementById("upload-files").files);
    const label = document.getElementById("upload-label").value;
    const source = document.getElementById("upload-source").value;
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    box.innerHTML = "";
    let failed = false;
    for (const file of files) {
      try { await uploadOne(file, form.dataset.match, files.length > 1 && label ? `${label} (${file.name})` : label, source); }
      catch (err) { failed = true; }
    }
    button.disabled = false;
    if (!failed) setTimeout(() => location.reload(), 800);
  });
})();
