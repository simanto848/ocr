/* Bidirectional text <-> source-image highlighting (loaded after app.js). */
/* ---------------- text ↔ source highlighting ---------------- */
let hlPending = null;

function _pageOf(n) {
  return (currentJob?.pages || []).find(p => p.page === n);
}

function setActiveLine(page, line, on, source) {
  const textEl = document.querySelector(`.hl-line[data-page="${page}"][data-line="${line}"]`);
  const boxEl = document.querySelector(`.hl-box[data-line="${line}"]`);
  if (textEl) textEl.classList.toggle("active", on);
  if (boxEl) boxEl.classList.toggle("active", on);
  const tip = $("hlTip");
  if (!on) { tip.hidden = true; return; }
  if (source === "image" && boxEl) {
    tip.textContent = boxEl.title || "";
    tip.hidden = !tip.textContent;
    tip.style.left = boxEl.style.left;
    tip.style.top = `calc(${boxEl.style.top} - 34px)`;
    if (textEl) textEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

function applyPendingHighlight() {
  // Keep the request: a second image load (page switch / re-render) must be
  // able to re-apply the same highlight after the overlay is rebuilt.
  if (!hlPending || hlPending.page !== currentPage) return;
  const p = hlPending;
  if (p.line != null) {
    setActiveLine(p.page, p.line, true, "text");
    return;
  }
  if (!p.box || p.box.length !== 4) return;
  const pg = _pageOf(p.page);
  if (!pg || !pg.boxes) return;
  let best = -1, bestDist = Infinity;
  pg.boxes.forEach((b, i) => {
    const c = b.box;
    if (!c) return;
    const d = Math.abs(c[0] - p.box[0]) + Math.abs(c[1] - p.box[1]);
    if (d < bestDist) { bestDist = d; best = i; }
  });
  if (best >= 0) {
    setActiveLine(p.page, best, true, "text");
    const el = document.querySelector(`.hl-box[data-line="${best}"]`);
    if (el) el.classList.add("mcq-active");
  }
}

function renderHighlights() {
  const overlay = $("hlOverlay");
  overlay.innerHTML = "";
  const img = $("preview");
  const pg = _pageOf(currentPage);
  if (!img.complete || !img.naturalWidth || !pg) return;
  const boxes = pg.boxes || [];
  if (!boxes.length) return;
  const size = pg.image_size || [img.naturalWidth, img.naturalHeight];
  const sx = img.clientWidth / size[0];
  const sy = img.clientHeight / size[1];
  boxes.forEach((b, i) => {
    const c = b.box || [];
    if (c.length !== 4 || !c.every(Number.isFinite)) return;
    const el = document.createElement("div");
    el.className = "hl-box";
    el.dataset.line = String(i);
    el.style.left = (c[0] * sx) + "px";
    el.style.top = (c[1] * sy) + "px";
    el.style.width = Math.max(3, (c[2] - c[0]) * sx) + "px";
    el.style.height = Math.max(3, (c[3] - c[1]) * sy) + "px";
    el.title = b.text || "";
    el.addEventListener("mouseenter", () => setActiveLine(currentPage, i, true, "image"));
    el.addEventListener("mouseleave", () => setActiveLine(currentPage, i, false, "image"));
    overlay.appendChild(el);
  });
  applyPendingHighlight();
}

