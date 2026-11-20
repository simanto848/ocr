/* DocExtract client — upload → poll → preview + text/JSON. Polished UX edition. */
const $ = (id) => document.getElementById(id);
const API_KEY = document.querySelector('meta[name="ocr-api-key"]')?.content || "";
const AUTH_HEADERS = API_KEY ? { "X-API-Key": API_KEY } : {};
let currentJob = null, currentPage = 1, currentTab = "md", pollTimer = null;
let batchJobs = [], batchTimer = null;

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function api(path, opts = {}) {
  opts.headers = { ...(opts.headers || {}), ...AUTH_HEADERS };
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
}

/* ---------------- theme ---------------- */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("ocr-theme", t); } catch (_) {}
}
try { applyTheme(localStorage.getItem("ocr-theme") || "light"); } catch (_) {}

/* ---------------- toasts ---------------- */
function toast(message, kind = "info", ms = 3000) {
  const box = $("toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  const icon = kind === "ok" ? "✓" : kind === "err" ? "!" : "i";
  el.innerHTML = `<span class="t-ico">${icon}</span><span>${esc(message)}</span>`;
  box.appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 260); }, ms);
}

/* ---------------- status ---------------- */
async function loadStatus() {
  try {
    const s = await api("/api/status");
    const vlmReady = !!(s.vlm && s.vlm.ready);
    const chip = $("engineChip");
    chip.classList.toggle("ready", vlmReady);
    chip.classList.toggle("off", !vlmReady);
    chip.querySelector(".status-text").textContent = vlmReady
      ? "PaddleOCR-VL ready"
      : `Tesseract ${(s.engine || "").split(" ")[1] || ""} · VLM off`;
    chip.title = vlmReady
      ? `Engine: PaddleOCR-VL · Languages: ${s.languages.join(", ")}`
      : "Start src/vlm_service.py in .venv-paddle for the accurate VLM engine";
  } catch (e) {
    const chip = $("engineChip");
    chip.classList.remove("ready"); chip.classList.add("off");
    chip.querySelector(".status-text").textContent = "engine unavailable";
  }
}

/* ---------------- helpers ---------------- */
function fileIcon(name) {
  const ext = (name.split(".").pop() || "").toLowerCase();
  if (ext === "pdf") return { cls: "pdf", label: "PDF" };
  if (["doc", "docx", "rtf", "odt"].includes(ext)) return { cls: "doc", label: "DOC" };
  if (["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "gif"].includes(ext)) return { cls: "", label: "IMG" };
  return { cls: "", label: (ext || "TXT").slice(0, 3).toUpperCase() };
}

function timeAgo(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr.replace(" ", "T"));
  if (isNaN(d)) return dateStr.slice(0, 10);
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return days < 30 ? `${days}d ago` : d.toLocaleDateString();
}

function wordCount(s) {
  const m = String(s || "").trim().match(/[\u0900-\u097F\u0980-\u09FF\w]+/g);
  return m ? m.length : 0;
}

/* ---------------- history ---------------- */
async function refreshHistory(activeId) {
  const jobs = await api("/api/history").catch(() => []);
  const box = $("history");
  $("historyCount").textContent = jobs.length;
  box.innerHTML = "";
  if (!jobs.length) {
    box.innerHTML = `<div class="history-empty">No files yet.<br>Upload one to see it here.</div>`;
    return;
  }
  for (const j of jobs) {
    const d = document.createElement("div");
    d.className = "hist-item" + (j.job_id === activeId ? " active" : "");
    const fi = fileIcon(j.filename);
    const done = j.status === "done", error = j.status === "error";
    const busy = !done && !error;
    const pillCls = done ? "done" : error ? "error" : "busy";
    let state = done ? "Done" : error ? "Error" : (j.progress?.percent ? `${Math.round(j.progress.percent)}%` : "Working");
    d.innerHTML =
      `<span class="hist-file-ico ${fi.cls}">${fi.label}</span>` +
      `<span class="hist-body"><span class="hist-name">${esc(j.filename)}</span>` +
      `<span class="hist-sub">${esc(timeAgo(j.created))}</span></span>` +
      `<span class="hist-pill ${pillCls}">${esc(state)}</span>` +
      (done ? `<button class="hist-mcq" title="Build MCQ dataset" aria-label="Build MCQ dataset from ${esc(j.filename)}">☑</button>` : '') +
      `<button class="hist-del" title="Delete ${esc(j.filename)}" aria-label="Delete ${esc(j.filename)}">` +
      `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M9 7V4h6v3m3 0l-1 13H7L6 7m4 4v6m4-6v6"/></svg></button>`;
    d.onclick = () => selectJob(j.job_id);
    const mcqBtn = d.querySelector(".hist-mcq");
    if (mcqBtn) mcqBtn.onclick = async (e) => {
      e.stopPropagation();
      try {
        toast("Building MCQ dataset…", "info", 1600);
        await api("/api/mcq/build", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: j.job_id })
        });
        if (typeof window.mcqShow === "function") window.mcqShow(j.job_id);
        refreshHistory(null);
      } catch (err) {
        toast("MCQ build failed: " + err.message, "err");
      }
    };
    const del = d.querySelector(".hist-del");
    del.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`Delete "${j.filename}" and all its extracted files?`)) return;
      try {
        await api("/api/delete?id=" + encodeURIComponent(j.job_id), { method: "POST" });
        batchJobs = batchJobs.filter(b => b.job_id !== j.job_id);
        renderBatch();
        if (currentJob && currentJob.job_id === j.job_id) {
          clearInterval(pollTimer);
          currentJob = null;
          $("docName").textContent = "No document yet";
          $("docSub").textContent = "Upload a file to get started";
          $("output").innerHTML = `<div class="output-empty"><svg class="empty-art" viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M24 20h72v80H24z"/><path d="M38 44h44M38 58h44M38 72h30"/></svg><strong>Extracted text appears here</strong><span>Copy, download or share it when processing finishes</span></div>`;
          $("resultMeta").hidden = true;
          $("preview").hidden = true;
          $("previewEmpty").hidden = false;
          $("previewEmpty").querySelector("strong").textContent = "Nothing to preview yet";
          $("footHint").textContent = "Ready";
        }
        toast("Deleted " + j.filename, "ok", 2200);
        await refreshHistory(null);
      } catch (err) {
        toast("Delete failed: " + err.message, "err");
      }
    };
    box.appendChild(d);
  }
}

/* ---------------- output ---------------- */
function sourceBadge(pg) {
  const digital = pg.source === "digital";
  return `<span class="src-badge ${digital ? "digital" : "ocr"}" title="${digital ? 'Read directly from the file — no OCR needed' : 'Recognised from the page image'}">${digital ? "digital text" : "OCR"}</span>`;
}

function inlineMd(s) {
  return esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function renderOutput(job) {
  const out = $("output");
  if (currentTab === "json") {
    out.innerHTML = `<pre><code>${esc(JSON.stringify(job.result_json || {}, null, 2))}</code></pre>`;
  } else {
    const md = job.markdown || "";
    let html = esc(md)
      .replace(/^### (.*)$/gm, "<h3>$1</h3>")
      .replace(/^## (.*)$/gm, "<h3>$1</h3>")
      .replace(/^# (.*)$/gm, "<h2>$1</h2>")
      .replace(/^---+$/gm, "<hr>");
    html = html.split("\n").map(line => {
      if (/^<h[23]>/.test(line)) return line;
      if (/^\s*[-*] /.test(line)) return `<div style="padding-left:12px">• ${line.replace(/^\s*[-*] /, "")}</div>`;
      return line;
    }).join("\n");
    for (const pg of (job.pages || [])) {
      html = html.replace(`<h3>Page ${pg.page}</h3>`, `<h3>Page ${pg.page} ${sourceBadge(pg)}</h3>`);
    }
    out.innerHTML = html || `<div class="output-empty"><strong>No text detected</strong><span>Try a clearer image or another OCR engine.</span></div>`;
  }
  $("tabMd").classList.toggle("active", currentTab === "md");
  $("tabJson").classList.toggle("active", currentTab === "json");
  $("tabMd").setAttribute("aria-selected", currentTab === "md");
  $("tabJson").setAttribute("aria-selected", currentTab === "json");

  // result meta chips
  const meta = $("resultMeta");
  if (job.status === "done") {
    meta.hidden = false;
    const pages = job.pages || [];
    const text = pages.map(p => p.text).join("\n");
    $("metaEngine").textContent = job.engine || "—";
    $("metaPages").textContent = `${pages.length} page${pages.length === 1 ? "" : "s"}`;
    $("metaWords").textContent = `${wordCount(text)} words`;
    $("metaChars").textContent = `${text.length.toLocaleString()} chars`;
  } else {
    meta.hidden = true;
  }
}

/* ---------------- progress ---------------- */
function stageLabel(job) {
  const p = job.progress || {};
  switch (p.stage) {
    case "queued": return "Waiting in queue…";
    case "preparing": return "Preparing document…";
    case "rendering": return p.of ? `Rendering page ${p.page} of ${p.of}` : "Rendering document…";
    case "ocr": return p.of ? `Reading page ${p.page} of ${p.of}` : "Recognising text…";
    case "vlm": return "Running PaddleOCR-VL…";
    case "done": return "Done";
    default: return "Working…";
  }
}

function renderProgress(job) {
  const box = $("progress");
  if (!job || job.status === "done" || job.status === "error") { box.hidden = true; return; }
  const p = job.progress || {};
  const pct = Math.round(p.percent || 0);
  box.hidden = false;
  $("progressLabel").textContent = stageLabel(job);
  $("progressPct").textContent = pct + "%";
  $("progressBar").style.width = pct + "%";
  $("progressDetail").textContent = p.of ? `Page ${p.page} of ${p.of} · this can take a moment on first run` : "";
}

/* ---------------- preview ---------------- */
function showPage() {
  if (!currentJob) return;
  const n = currentJob.n_pages || 0;
  $("pageLabel").textContent = n ? `${currentPage} / ${n}` : "–";
  $("prevPage").disabled = currentPage <= 1;
  $("nextPage").disabled = currentPage >= n;
  if (!n) return;
  const url = `/api/preview?job=${currentJob.job_id}&page=${currentPage}`;
  const probe = new Image();
  probe.onload = () => {
    const img = $("preview");
    img.src = url; img.hidden = false; $("previewEmpty").hidden = true;
  };
  probe.onerror = () => {
    $("preview").hidden = true; $("previewEmpty").hidden = false;
    $("previewEmpty").querySelector("strong").textContent = "Preparing preview…";
  };
  probe.src = url;
}

/* ---------------- job selection ---------------- */
async function selectJob(id) {
  clearInterval(pollTimer);
  let job;
  try { job = await api(`/api/job?id=${id}`); }
  catch (e) { toast("Could not load that job", "err"); return; }
  currentJob = job; currentPage = 1;
  renderBatch();
  $("docName").textContent = job.filename;
  const fi = fileIcon(job.filename);
  $("docIcon").innerHTML = `<span style="font-size:9px;font-weight:800">${fi.label}</span>`;
  $("docSub").textContent = job.status === "done"
    ? `${job.engine || "OCR"} · ${job.n_pages || 0} page${job.n_pages === 1 ? "" : "s"}`
    : "Processing…";

  if (job.status === "done") {
    renderProgress(job); renderOutput(job); showPage();
    $("footHint").textContent = "Ready · select text to copy";
  } else if (job.status === "error") {
    renderProgress(job); showPage();
    $("resultMeta").hidden = true;
    $("output").innerHTML = `<div class="output-empty"><strong>Processing failed</strong><span>${esc(job.error || "Unknown error")}</span></div>`;
    $("footHint").textContent = "Error";
    toast(job.error || "Processing failed", "err");
  } else {
    renderProgress(job); showPage();
    $("resultMeta").hidden = true;
    $("output").innerHTML = `<div class="output-empty"><strong>Extracting text…</strong><span>Results will appear here when done</span></div>`;
    $("footHint").textContent = "Processing…";
    // Batch jobs are already polled by pollBatch(); avoid double polling.
    if (batchJobs.some(j => j.job_id === id)) {
      renderBatch();
    } else {
      pollTimer = setInterval(async () => {
        const j = await api(`/api/job?id=${id}`).catch(() => null);
        if (!j) return;
        currentJob = j;
        renderProgress(j); showPage(); refreshHistory(id);
        if (j.status === "done" || j.status === "error") { clearInterval(pollTimer); selectJob(id); }
      }, 1400);
    }
  }
  refreshHistory(id);
}

/* ---------------- upload ---------------- */
/* ---------------- batch upload ---------------- */
function renderBatch() {
  const box = $("batchBox");
  if (!batchJobs.length) { box.hidden = true; return; }
  box.hidden = false;
  const done = batchJobs.filter(j => j.status === "done").length;
  const failed = batchJobs.filter(j => j.status === "error").length;
  $("batchSummary").textContent = `${done}/${batchJobs.length} done${failed ? ` · ${failed} failed` : ""}`;
  $("batchList").innerHTML = batchJobs.map(j => {
    const fi = fileIcon(j.filename);
    const state = j.status === "done" ? "Done" : j.status === "error" ? "Error" : `${Math.round(j.percent || 0)}%`;
    const cls = j.status === "done" ? "done" : j.status === "error" ? "error" : "busy";
    const barCls = j.status === "done" ? "done" : j.status === "error" ? "error" : "";
    const width = j.status === "done" || j.status === "error" ? 100 : (j.percent || 0);
    return `<div class="batch-item ${j.job_id === currentJob?.job_id ? "active" : ""}" data-id="${j.job_id}">` +
      `<div class="batch-row"><span class="hist-file-ico ${fi.cls}">${fi.label}</span>` +
      `<span class="batch-name">${esc(j.filename)}</span>` +
      `<span class="batch-state ${cls}">${esc(state)}</span></div>` +
      `<div class="batch-track"><div class="batch-bar ${barCls}" style="width:${width}%"></div></div></div>`;
  }).join("");
  $("batchList").querySelectorAll(".batch-item").forEach(el => {
    el.onclick = () => selectJob(el.dataset.id);
  });
}

async function pollBatch() {
  let changed = false;
  for (const j of batchJobs) {
    if (j.status === "done" || j.status === "error") continue;
    const d = await api(`/api/job?id=${j.job_id}`).catch(() => null);
    if (!d) continue;
    j.status = d.status;
    j.percent = (d.progress?.percent) || 0;
    j.error = d.error;
    changed = true;
  }
  if (changed) {
    renderBatch();
    refreshHistory(null);
    // refresh the currently open job if it's in this batch
    if (currentJob && batchJobs.some(j => j.job_id === currentJob.job_id && (j.status === "done" || j.status === "error"))) {
      selectJob(currentJob.job_id);
    }
  }
  const pending = batchJobs.some(j => j.status !== "done" && j.status !== "error");
  if (!pending) {
    clearInterval(batchTimer); batchTimer = null;
    const done = batchJobs.filter(j => j.status === "done").length;
    const failed = batchJobs.length - done;
    toast(`Batch finished · ${done} done${failed ? ` · ${failed} failed` : ""}`, failed ? "err" : "ok", 4000);
    renderBatch();
  }
}

async function uploadFiles(files) {
  const list = [...(files || [])].filter(Boolean);
  if (!list.length) return;
  const fd = new FormData();
  list.forEach(f => fd.append("file", f, f.name));
  fd.append("lang", $("langSelect").value);
  fd.append("engine", $("engineSelect").value);

  $("progress").hidden = false;
  $("progressLabel").textContent = list.length > 1 ? `Uploading ${list.length} files…` : "Uploading…";
  $("progressPct").textContent = "";
  $("progressBar").style.width = "100%";
  $("progressDetail").textContent = list.length > 1 ? list.map(f => f.name).join(", ").slice(0, 90) : list[0].name;
  $("preview").hidden = true;
  $("previewEmpty").hidden = false;
  $("previewEmpty").querySelector("strong").textContent = "Uploading your files…";

  try {
    const r = await fetch("/api/upload", { method: "POST", body: fd, headers: AUTH_HEADERS });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "upload failed");
    batchJobs = (j.jobs || [{ job_id: j.job_id, filename: list[0].name }]).map(x => ({
      job_id: x.job_id, filename: x.filename, status: "queued", percent: 0,
    }));
    (j.errors || []).forEach(e => toast(`Skipped ${e.filename}: ${e.error}`, "err", 4000));
    toast(`Queued ${batchJobs.length} file${batchJobs.length === 1 ? "" : "s"}`, "ok", 2200);
    renderBatch();
    await refreshHistory(null);
    clearInterval(batchTimer);
    batchTimer = setInterval(pollBatch, 1200);
    selectJob(batchJobs[0].job_id);
  } catch (e) {
    $("progress").hidden = true;
    toast(`Upload failed: ${e.message}`, "err", 5000);
  }
}

/* single-file wrapper kept for compatibility */
function uploadFile(file) { return uploadFiles([file]); }

/* ---------------- init / events ---------------- */
function init() {
  const drop = $("drop"), fi = $("fileInput");

  drop.onclick = () => fi.click();
  drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") fi.click(); };
  fi.onchange = () => { uploadFiles([...fi.files]); fi.value = ""; };

  // window-wide drag & drop with overlay
  const overlay = $("dragOverlay");
  let dragDepth = 0;
  window.addEventListener("dragenter", e => { e.preventDefault(); dragDepth++; overlay.classList.add("show"); });
  window.addEventListener("dragover", e => e.preventDefault());
  window.addEventListener("dragleave", e => { e.preventDefault(); if (--dragDepth <= 0) { dragDepth = 0; overlay.classList.remove("show"); } });
  window.addEventListener("drop", e => {
    e.preventDefault(); dragDepth = 0; overlay.classList.remove("show");
    drop.classList.remove("over");
    const fs = [...(e.dataTransfer?.files || [])];
    if (fs.length) uploadFiles(fs);
  });
  document.addEventListener("paste", e => {
    const fs = [...(e.clipboardData?.files || [])];
    if (fs.length) uploadFiles(fs);
  });

  $("prevPage").onclick = () => { if (currentPage > 1) { currentPage--; showPage(); } };
  $("nextPage").onclick = () => { if (currentJob && currentPage < currentJob.n_pages) { currentPage++; showPage(); } };
  $("reloadJob").onclick = () => { if (currentJob) { selectJob(currentJob.job_id); toast("Refreshed", "info", 1600); } };
  $("tabMd").onclick = () => { currentTab = "md"; if (currentJob) renderOutput(currentJob); };
  $("tabJson").onclick = () => { currentTab = "json"; if (currentJob) renderOutput(currentJob); };

  // copy
  $("btnCopy").onclick = async () => {
    if (!currentJob || currentJob.status !== "done") return;
    const t = currentTab === "json" ? JSON.stringify(currentJob.result_json, null, 2) : currentJob.markdown;
    try { await navigator.clipboard.writeText(t); toast("Copied to clipboard", "ok", 1800); }
    catch (_) { toast("Copy failed — select the text manually", "err"); }
  };

  // download dropdown
  const dlMenu = $("dlMenu");
  $("btnDl").onclick = (e) => { e.stopPropagation(); dlMenu.hidden = !dlMenu.hidden; };
  dlMenu.querySelectorAll("button").forEach(b => b.onclick = () => {
    if (!currentJob || currentJob.status !== "done") return;
    window.location = `/api/download?job=${currentJob.job_id}&format=${b.dataset.fmt}`;
    dlMenu.hidden = true;
    toast(`Downloading ${b.dataset.fmt.toUpperCase()}`, "info", 1800);
  });
  document.addEventListener("click", e => {
    if (!e.target.closest(".download-wrap")) dlMenu.hidden = true;
  });

  // share
  $("btnShare").onclick = async () => {
    if (!currentJob || currentJob.status !== "done") return;
    const text = currentTab === "json" ? JSON.stringify(currentJob.result_json, null, 2) : currentJob.markdown;
    if (navigator.share) {
      try { await navigator.share({ title: currentJob.filename, text: text.slice(0, 2000) }); }
      catch (_) {}
    } else {
      try { await navigator.clipboard.writeText(text); toast("Shared text copied", "ok", 1800); }
      catch (_) { toast("Sharing not available", "err"); }
    }
  };

  // theme + help
  $("themeToggle").onclick = () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  $("helpBtn").onclick = () => $("helpModal").hidden = false;
  $("helpClose").onclick = () => $("helpModal").hidden = true;
  $("helpModal").onclick = e => { if (e.target === $("helpModal")) $("helpModal").hidden = true; };

  // keyboard shortcuts
  document.addEventListener("keydown", e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); fi.click(); }
    if (e.key === "Escape") { $("helpModal").hidden = true; dlMenu.hidden = true; }
    if (e.key === "ArrowLeft" && currentPage > 1) { currentPage--; showPage(); }
    if (e.key === "ArrowRight" && currentJob && currentPage < currentJob.n_pages) { currentPage++; showPage(); }
  });

  loadStatus();
  refreshHistory(null);
}
document.addEventListener("DOMContentLoaded", init);
