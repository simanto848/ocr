/* MCQ dataset view — upload a question paper, review extracted questions,
   then export a RAG / fine-tuning dataset. Vanilla JS, no build step. */
(() => {
  const $ = (id) => document.getElementById(id);
  const AUTH = (() => {
    const k = document.querySelector('meta[name="ocr-api-key"]')?.content;
    return k ? { "X-API-Key": k } : {};
  })();

  const M = {
    jobId: null,
    ds: null,
    filter: "all",
    search: "",
    timers: {},
    poll: null,
    busy: false,
  };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function toastMsg(msg, kind = "info", ms = 2600) {
    if (typeof window.toast === "function") window.toast(msg, kind, ms);
    else console.log(`[${kind}] ${msg}`);
  }

  async function mApi(path, opts = {}) {
    opts.headers = { ...(opts.headers || {}), ...AUTH };
    const r = await fetch(path, opts);
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.error || r.statusText || `HTTP ${r.status}`);
    }
    return r.json();
  }

  function timeAgo(dateStr) {
    if (!dateStr) return "";
    const d = new Date(dateStr.replace(" ", "T"));
    if (isNaN(d)) return String(dateStr).slice(0, 10);
    const mins = Math.round((Date.now() - d.getTime()) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.round(hrs / 24);
    return days < 30 ? `${days}d ago` : d.toLocaleDateString();
  }

  /* ---------------- view switching ---------------- */
  function showView(which) {
    const isText = which === "text";
    $("viewText").hidden = !isText;
    $("viewMcq").hidden = isText;
    $("navText").classList.toggle("active", isText);
    $("navMcq").classList.toggle("active", !isText);
    $("navText").setAttribute("aria-selected", String(isText));
    $("navMcq").setAttribute("aria-selected", String(!isText));
    try { localStorage.setItem("ocr-view", which); } catch (_) {}
    if (!isText) refreshHistory();
  }

  /* ---------------- loading / empty states ---------------- */
  function showPane(pane) {
    $("mcqEmpty").hidden = pane !== "empty";
    $("mcqLoading").hidden = pane !== "loading";
    $("mcqWork").hidden = pane !== "work";
  }

  function setLoading(label, pct, detail) {
    showPane("loading");
    $("mcqProgLabel").textContent = label || "Working…";
    $("mcqProgPct").textContent = `${Math.round(pct || 0)}%`;
    $("mcqProgBar").style.width = `${Math.max(2, pct || 0)}%`;
    $("mcqProgDetail").textContent = detail || "";
  }

  /* ---------------- history ---------------- */
  async function refreshHistory() {
    let jobs = [];
    try { jobs = await mApi("/api/history"); } catch (_) { return; }
    const mcq = jobs.filter((j) => j.kind === "mcq" || j.mcq);
    $("mcqCount").textContent = String(mcq.length);
    const box = $("mcqHistory");
    box.innerHTML = "";
    if (!mcq.length) {
      box.innerHTML = '<p class="hist-empty">No MCQ sets yet</p>';
      return;
    }
    for (const j of mcq) {
      const el = document.createElement("div");
      el.className = "hist-item";
      el.setAttribute("role", "button");
      el.tabIndex = 0;
      if (j.job_id === M.jobId) el.classList.add("active");
      const n = j.mcq?.stats?.included;
      el.innerHTML =
        '<span class="hist-file-ico">MCQ</span>' +
        '<span class="hist-body"><span class="hist-name"></span>' +
        '<span class="hist-sub"></span></span>' +
        '<button class="hist-del text-del" title="Delete dataset" aria-label="Delete dataset">×</button>';
      el.querySelector(".hist-name").textContent = j.filename || j.job_id;
      el.querySelector(".hist-sub").textContent =
        `${j.status === "done" ? `${n ?? 0} questions` : j.status} · ${timeAgo(j.created)}`;
      el.onclick = () => {
        if (j.status === "done") loadJob(j.job_id);
        else if (j.status === "error") toastMsg(j.error || "Job failed", "err");
        else pollJob(j.job_id, j.filename);
      };
      el.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); el.click(); }
      };
      el.querySelector(".hist-del").onkeydown = (e) => e.stopPropagation();
      el.querySelector(".hist-del").onclick = async (e) => {
        e.stopPropagation();
        if (!window.confirm(`Delete "${j.filename}" and its dataset?`)) return;
        try {
          await mApi("/api/delete?id=" + encodeURIComponent(j.job_id), { method: "POST" });
          if (M.jobId === j.job_id) { M.jobId = null; M.ds = null; showPane("empty"); }
          toastMsg("Deleted", "ok");
          refreshHistory();
        } catch (err) { toastMsg("Delete failed: " + err.message, "err"); }
      };
      box.appendChild(el);
    }
  }

  /* ---------------- AI providers ---------------- */
  let providers = [];

  async function loadProviders(preferred) {
    let data;
    try { data = await mApi("/api/ai/providers"); }
    catch (e) { toastMsg(`Could not load providers: ${e.message}`, "err"); return; }
    providers = data.providers || [];
    const sel = $("mcqProvider");
    sel.innerHTML = "";
    providers.forEach((p) => {
      const o = document.createElement("option");
      o.value = p.id;
      o.textContent = p.name + (p.has_key ? " ✓" : "");
      sel.appendChild(o);
    });
    const want = preferred || localStorage.getItem("ocr-ai-provider") || "ollama";
    if (providers.some((p) => p.id === want)) sel.value = want;
    updateProviderUI();
    await loadModels();
  }

  function currentProvider() {
    return providers.find((p) => p.id === $("mcqProvider").value) || null;
  }

  function updateProviderUI() {
    const p = currentProvider();
    if (!p) return;
    $("mcqAiUrl").value = p.base_url || "";
    $("mcqAiKey").value = "";
    $("mcqAiKey").placeholder = p.has_key
      ? "leave blank to keep the saved key"
      : "paste API key / token (if required)";
    $("mcqAiHint").textContent = p.hint || "";
    try { localStorage.setItem("ocr-ai-provider", p.id); } catch (_) {}
  }

  async function loadModels() {
    const pid = $("mcqProvider").value;
    if (!pid) return;
    const list = $("mcqModelList");
    const field = $("mcqModel");
    list.innerHTML = "";
    field.placeholder = "loading models…";
    try {
      const r = await mApi("/api/ai/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: pid }),
      });
      r.models.forEach((m) => {
        const o = document.createElement("option");
        o.value = m.id;
        o.label = m.label;
        list.appendChild(o);
      });
      const saved = localStorage.getItem("ocr-ai-model-" + pid);
      const pick = saved || (r.models.some((m) => m.id === r.default) ? r.default
                             : r.models[0]?.id || "");
      if (pick) field.value = pick;
      field.placeholder = r.models.length
        ? `choose or type a model (${r.models.length} found)`
        : "type a model name";
      $("mcqAiHint").textContent = r.models.length
        ? `${r.models.length} model(s) available`
        : "No models returned — type the model name manually.";
    } catch (e) {
      field.placeholder = "type a model name";
      $("mcqAiHint").textContent = `Model list unavailable: ${e.message}`;
    }
  }

  function aiConfig() {
    const p = currentProvider() || {};
    const body = { provider: p.id || $("mcqProvider").value };
    const key = $("mcqAiKey").value.trim();
    const url = $("mcqAiUrl").value.trim();
    if (key) body.api_key = key;
    if (url && url !== p.base_url) body.base_url = url;
    return body;
  }

  async function testAi() {
    const model = $("mcqModel").value.trim();
    const body = { ...aiConfig(), model };
    $("mcqTestAi").textContent = "Testing…";
    try {
      const r = await mApi("/api/ai/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      toastMsg(`Connected · ${r.models} model(s) · ${r.sample || "OK"}`, "ok", 3200);
    } catch (e) {
      toastMsg(`Connection failed: ${e.message}`, "err", 4200);
    } finally {
      $("mcqTestAi").textContent = "Test connection";
    }
  }

  async function saveAiConnection() {
    const p = currentProvider();
    if (!p) return;
    const body = { id: p.id };
    if ($("mcqAiKey").value.trim()) body.api_key = $("mcqAiKey").value.trim();
    if ($("mcqAiUrl").value.trim()) body.base_url = $("mcqAiUrl").value.trim();
    if ($("mcqModel").value.trim()) body.default_model = $("mcqModel").value.trim();
    try {
      await mApi("/api/ai/provider/configure", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      toastMsg("Connection saved", "ok");
      await loadProviders(p.id);
    } catch (e) {
      toastMsg(`Could not save: ${e.message}`, "err");
    }
  }

  function toggleAiBox() {
    const on = $("mcqAiMode").value !== "heuristic";
    $("mcqAiBox").hidden = !on;
    if (on && !providers.length) loadProviders();
  }

  /* ---------------- upload ---------------- */
  async function upload(file) {
    if (!file || M.busy) return;
    M.busy = true;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", "mcq");
    fd.append("answer_mode", $("mcqAnswerMode").value);
    fd.append("lang", $("mcqLangSelect").value);
    fd.append("engine", $("mcqEngineSelect").value);
    const aiMode = $("mcqAiMode").value;
    fd.append("ai_mode", aiMode);
    if (aiMode !== "heuristic") {
      const p = currentProvider();
      fd.append("ai_provider", p ? p.id : $("mcqProvider").value);
      const model = $("mcqModel").value.trim();
      if (!model) {
        M.busy = false;
        toastMsg("Choose a model (or type one) before uploading.", "err");
        return;
      }
      fd.append("ai_model", model);
      try { localStorage.setItem("ocr-ai-model-" + (p?.id || ""), model); } catch (_) {}
    }
    setLoading(`Uploading ${file.name}`, 1, "Sending file…");
    try {
      const r = await mApi("/api/upload", { method: "POST", body: fd });
      if (r.errors && r.errors.length) {
        toastMsg(r.errors[0].error || "Unsupported file", "err");
      }
      pollJob(r.job_ids[0], file.name);
    } catch (e) {
      M.busy = false;
      showPane("empty");
      toastMsg(`Upload failed: ${e.message}`, "err");
    }
  }

  async function pollJob(jid, filename = "document") {
    M.busy = true;
    const started = Date.now();
    while (true) {
      let job;
      try {
        job = await mApi(`/api/job?id=${encodeURIComponent(jid)}`);
      } catch (e) {
        M.busy = false;
        showPane("empty");
        toastMsg(`Could not read job: ${e.message}`, "err");
        return;
      }
      const p = job.progress || {};
      const detail = p.stage
        ? `${p.stage}${p.of ? ` · page ${p.page}/${p.of}` : ""}`
        : "Waiting for the queue…";
      setLoading(`Extracting ${filename}`, p.percent || 3, detail);
      if (job.status === "done") {
        M.busy = false;
        await loadJob(jid);
        return;
      }
      if (job.status === "error") {
        M.busy = false;
        showPane("empty");
        toastMsg(job.error || "Extraction failed", "err");
        return;
      }
      if (Date.now() - started > 15 * 60 * 1000) {
        M.busy = false;
        showPane("empty");
        toastMsg("Timed out — check the Extract text tab for progress.", "err");
        return;
      }
      await sleep(700);
    }
  }

  /* ---------------- dataset render ---------------- */
  async function loadJob(jid) {
    try {
      const data = await mApi(`/api/mcq/job?id=${encodeURIComponent(jid)}`);
      M.jobId = jid;
      M.ds = data.dataset;
      M.method = data.job?.mcq?.method || "heuristic";
      M.ai = data.job?.mcq?.ai || null;
      M.filter = "all";
      M.search = "";
      $("mcqSearch").value = "";
      document.querySelectorAll("#mcqFilters .segment").forEach((b) => {
        b.classList.toggle("active", b.dataset.filter === "all");
      });
      render();
      refreshHistory();
      if (!M.ds || !M.ds.items.length) {
        showPane("work");
        toastMsg("No multiple-choice questions found — try a different answer layout.", "err", 4200);
      }
    } catch (e) {
      showPane("empty");
      toastMsg(`Could not load dataset: ${e.message}`, "err");
    }
  }

  function render() {
    const ds = M.ds;
    if (!ds) { showPane("empty"); return; }
    showPane("work");
    const st = ds.manifest?.stats || {};
    $("mcqTitle").textContent = ds.manifest?.name || "MCQ dataset";
    const methodLabel = M.method === "ai" ? "AI" :
                        M.method === "hybrid" ? "AI + heuristic" : "heuristic";
    const aiLabel = M.ai?.provider
      ? ` · ${M.ai.provider}${M.ai.model ? "/" + M.ai.model : ""}` : "";
    $("mcqSub").textContent =
      `${st.included ?? ds.items.length} questions · ` +
      `${st.with_answer ?? 0} with answers · ` +
      `${methodLabel}${aiLabel} · ` +
      `${Object.keys(st.languages || {}).filter((k) => k !== "unknown").join(", ") || "language unknown"}`;
    renderStats(st);
    renderList();
  }

  function renderStats(st) {
    const cells = [
      { k: st.included ?? 0, l: "questions" },
      { k: st.with_answer ?? 0, l: "with answer", cls: "good" },
      { k: st.missing_answer ?? 0, l: "missing answer", cls: st.missing_answer ? "bad" : "" },
      { k: st.needs_review ?? 0, l: "need review", cls: st.needs_review ? "warn" : "" },
      { k: st.avg_confidence ?? 0, l: "avg confidence" },
    ];
    const box = $("mcqStats");
    box.innerHTML = "";
    for (const c of cells) {
      const d = document.createElement("div");
      d.className = `mcq-stat ${c.cls || ""}`;
      const b = document.createElement("b");
      b.textContent = String(c.k);
      const s = document.createElement("span");
      s.textContent = c.l;
      d.append(b, s);
      box.appendChild(d);
    }
  }

  function itemText(it) {
    return (it.question || "") + " " + (it.options || []).map((o) => o.text).join(" ");
  }

  function visibleItems() {
    const q = M.search.trim().toLowerCase();
    return (M.ds?.items || []).filter((it) => {
      if (M.filter === "review" && !it.needs_review) return false;
      if (M.filter === "missing" && (it.answer || {}).label) return false;
      if (q && !itemText(it).toLowerCase().includes(q)) return false;
      return true;
    });
  }

  function renderList() {
    const list = $("mcqList");
    list.innerHTML = "";
    const items = visibleItems();
    $("mcqVisible").textContent = `${items.length} shown`;
    if (!items.length) {
      const p = document.createElement("p");
      p.className = "hist-empty";
      p.textContent = M.ds?.items.length
        ? "Nothing matches this filter or search."
        : "No questions were detected in this document.";
      list.appendChild(p);
      return;
    }
    items.forEach((it, i) => list.appendChild(buildCard(it, i)));
  }

  function buildCard(it, index) {
    const card = document.createElement("article");
    card.className = "mcq-card" + (it.include === false ? " excluded" : "");
    card.dataset.id = it.id;
    card.dataset.uid = it.uid || "";

    /* header */
    const head = document.createElement("div");
    head.className = "mcq-card-head";
    const num = document.createElement("span");
    num.className = "mcq-num";
    num.textContent = `Q${it.number ?? index + 1}`;
    head.appendChild(num);

    const src = document.createElement("span");
    src.className = "mcq-src";
    const s = it.source || {};
    src.textContent = [
      s.page ? `page ${s.page}` : "",
      it.language || "",
      typeof it.confidence === "number" ? `${Math.round(it.confidence * 100)}%` : "",
    ].filter(Boolean).join(" · ");
    head.appendChild(src);

    const badge = document.createElement("span");
    badge.className = "mcq-badge";
    head.appendChild(badge);

    const inc = document.createElement("label");
    inc.className = "mcq-include";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "mcq-include-box";
    cb.checked = it.include !== false;
    cb.onchange = () => {
      card.classList.toggle("excluded", !cb.checked);
      saveCard(card, { include: cb.checked });
    };
    inc.append(cb, document.createTextNode(" include"));
    head.appendChild(inc);
    card.appendChild(head);

    /* question */
    const q = document.createElement("textarea");
    q.className = "mcq-question";
    q.rows = 2;
    q.setAttribute("aria-label", `Question ${it.number ?? index + 1} text`);
    q.value = it.question || "";
    q.oninput = () => scheduleSave(card);
    card.appendChild(q);

    /* options */
    const opts = document.createElement("div");
    opts.className = "mcq-options";
    const group = `ans-${it.id}`;
    for (const o of it.options || []) {
      const row = document.createElement("label");
      row.className = "mcq-opt";
      row.dataset.label = o.label;
      if ((it.answer || {}).label === o.label) row.classList.add("correct");

      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = group;
      radio.value = o.label;
      radio.checked = (it.answer || {}).label === o.label;
      radio.onchange = () => {
        opts.querySelectorAll(".mcq-opt").forEach((r) =>
          r.classList.toggle("correct", r.dataset.label === o.label));
        badgeFor(card, { answer: { label: o.label }, needs_review: false });
        saveCard(card, { answer: o.label });
      };

      const lab = document.createElement("span");
      lab.className = "opt-lab";
      lab.textContent = o.label;

      const text = document.createElement("input");
      text.className = "opt-text";
      text.setAttribute("aria-label", `Option ${o.label}`);
      text.value = o.text || "";
      text.oninput = () => scheduleSave(card);

      row.append(radio, lab, text);
      opts.appendChild(row);
    }
    card.appendChild(opts);

    /* explanation / passage */
    const more = document.createElement("details");
    more.className = "mcq-more";
    const sum = document.createElement("summary");
    sum.textContent = "Explanation & passage";
    const expl = document.createElement("textarea");
    expl.className = "mcq-expl";
    expl.rows = 2;
    expl.placeholder = "Explanation (optional)";
    expl.setAttribute("aria-label", "Explanation");
    expl.value = it.explanation || "";
    expl.oninput = () => scheduleSave(card);
    more.append(sum, expl);
    if (it.passage) {
      const pass = document.createElement("textarea");
      pass.className = "mcq-expl mcq-passage";
      pass.rows = 2;
      pass.placeholder = "Comprehension passage";
      pass.setAttribute("aria-label", "Comprehension passage");
      pass.value = it.passage;
      pass.oninput = () => scheduleSave(card);
      more.appendChild(pass);
    }
    card.appendChild(more);

    /* footer */
    const foot = document.createElement("div");
    foot.className = "mcq-card-foot";
    const sref = it.source || {};
    if (Array.isArray(sref.bbox) && sref.bbox.length === 4) {
      const jump = document.createElement("button");
      jump.type = "button";
      jump.className = "mcq-btn";
      jump.textContent = "📍 Source";
      jump.title = "Locate this question in the original page";
      jump.onclick = () => {
        if (typeof window.showSource === "function") {
          window.showSource(sref.page, sref.bbox, M.jobId);
        }
      };
      foot.appendChild(jump);
    }
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "mcq-btn";
    clear.textContent = "Clear answer";
    clear.onclick = () => {
      opts.querySelectorAll(".mcq-opt").forEach((r) => {
        r.classList.remove("correct");
        r.querySelector('input[type="radio"]').checked = false;
      });
      badgeFor(card, { answer: null, needs_review: true });
      saveCard(card, { answer: null });
    };
    const msg = document.createElement("span");
    msg.className = "mcq-msg";
    foot.append(clear, msg);
    card.appendChild(foot);

    badgeFor(card, it);
    return card;
  }

  function badgeFor(card, it) {
    const badge = card.querySelector(".mcq-badge");
    if (!badge) return;
    const hasAnswer = !!(it.answer || {}).label;
    if (!hasAnswer) {
      badge.className = "mcq-badge missing";
      badge.textContent = "no answer";
    } else if (it.needs_review) {
      badge.className = "mcq-badge review";
      badge.textContent = "review";
    } else {
      badge.className = "mcq-badge ok";
      badge.textContent = "ready";
    }
  }

  /* ---------------- saving ---------------- */
  function collect(card) {
    return {
      question: card.querySelector(".mcq-question").value,
      explanation: card.querySelector(".mcq-expl")?.value || "",
      passage: card.querySelector(".mcq-passage")?.value || "",
      include: card.querySelector(".mcq-include-box").checked,
      options: [...card.querySelectorAll(".mcq-opt")].map((r) => ({
        label: r.dataset.label,
        text: r.querySelector(".opt-text").value,
      })),
    };
  }

  function setMsg(card, text, cls = "") {
    const m = card.querySelector(".mcq-msg");
    if (!m) return;
    m.textContent = text;
    m.className = `mcq-msg ${cls}`;
  }

  function scheduleSave(card) {
    card.classList.add("saving");
    const id = card.dataset.id;
    clearTimeout(M.timers[id]);
    M.timers[id] = setTimeout(() => saveCard(card), 650);
  }

  async function saveCard(card, extra = {}) {
    if (!M.jobId) return;
    const id = card.dataset.id;
    clearTimeout(M.timers[id]);
    const payload = { job_id: M.jobId, item_id: id, ...collect(card), ...extra };
    setMsg(card, "Saving…");
    try {
      const r = await mApi("/api/mcq/item", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      card.classList.remove("saving");
      setMsg(card, "Saved", "ok");
      if (r.item) {
        badgeFor(card, r.item);
        Object.assign(
          (M.ds.items || []).find((x) => x.id === id) || {},
          r.item);
      }
      if (r.stats) {
        M.ds.manifest = M.ds.manifest || {};
        M.ds.manifest.stats = r.stats;
        renderStats(r.stats);
      }
    } catch (e) {
      card.classList.remove("saving");
      setMsg(card, "Save failed", "err");
      toastMsg(`Save failed: ${e.message}`, "err");
    }
  }

  async function commitDatasetName() {
    const input = $("mcqNameInput");
    const name = input.value.trim();
    const original = M.ds?.manifest?.name || "";
    input.hidden = true;
    $("mcqTitle").hidden = false;
    $("mcqEditName").hidden = false;
    if (!name || name === original || !M.jobId) return;
    try {
      const r = await mApi("/api/mcq/rename", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: M.jobId, name }),
      });
      if (M.ds) M.ds.manifest.name = r.manifest.name;
      $("mcqTitle").textContent = r.manifest.name;
      toastMsg("Dataset renamed", "ok");
    } catch (e) {
      $("mcqTitle").textContent = original;
      toastMsg(`Rename failed: ${e.message}`, "err");
    }
  }

  async function addCustomProvider() {
    const body = {
      name: $("aiNewName").value.trim(),
      base_url: $("aiNewUrl").value.trim(),
      kind: $("aiNewKind").value,
      api_key: $("aiNewKey").value.trim(),
      default_model: $("aiNewModel").value.trim(),
    };
    if (!body.name || !body.base_url) {
      toastMsg("Name and base URL are required", "err");
      return;
    }
    try {
      const p = await mApi("/api/ai/provider", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      $("aiProviderModal").hidden = true;
      ["aiNewName", "aiNewUrl", "aiNewKey", "aiNewModel"].forEach((id) => { $(id).value = ""; });
      await loadProviders(p.id);
      toastMsg(`${p.name} added`, "ok");
    } catch (e) {
      toastMsg(`Could not add provider: ${e.message}`, "err");
    }
  }

  /* ---------------- export ---------------- */
  function download(fmt) {
    if (!M.jobId) return;
    window.location = `/api/mcq/download?id=${encodeURIComponent(M.jobId)}&format=${fmt}`;
    toastMsg(`Downloading ${fmt.toUpperCase()}`, "info", 1600);
  }

  /* ---------------- wiring ---------------- */
  function init() {
    if (!$("viewMcq")) return;

    $("navText").onclick = () => showView("text");
    $("navMcq").onclick = () => showView("mcq");

    $("mcqAiMode").onchange = toggleAiBox;
    $("mcqProvider").onchange = () => { updateProviderUI(); loadModels(); };
    $("mcqModel").onchange = () => {
      const p = currentProvider();
      if (p) { try { localStorage.setItem("ocr-ai-model-" + p.id, $("mcqModel").value); } catch (_) {} }
    };
    $("mcqRefreshModels").onclick = loadModels;
    $("mcqTestAi").onclick = testAi;
    $("mcqSaveConn").onclick = saveAiConnection;
    $("mcqAddProvider").onclick = () => { $("aiProviderModal").hidden = false; };
    $("aiProviderClose").onclick = () => { $("aiProviderModal").hidden = true; };
    $("aiProviderModal").onclick = (e) => {
      if (e.target === $("aiProviderModal")) $("aiProviderModal").hidden = true;
    };
    $("aiNewSave").onclick = addCustomProvider;
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !$("aiProviderModal").hidden) {
        $("aiProviderModal").hidden = true;
      }
    });
    if ($("mcqAiMode").value !== "heuristic") toggleAiBox();

    const input = $("mcqFileInput");
    const drop = $("mcqDrop");
    drop.onclick = () => input.click();
    drop.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
    };
    input.onchange = () => {
      if (input.files && input.files[0]) upload(input.files[0]);
      input.value = "";
    };
    ["dragenter", "dragover"].forEach((ev) =>
      drop.addEventListener(ev, (e) => {
        e.preventDefault();
        drop.classList.add("over");
      }));
    ["dragleave", "drop"].forEach((ev) =>
      drop.addEventListener(ev, (e) => {
        e.preventDefault();
        drop.classList.remove("over");
      }));
    drop.addEventListener("drop", (e) => {
      const f = e.dataTransfer?.files?.[0];
      if (f) upload(f);
    });
    document.addEventListener("paste", (e) => {
      if ($("viewMcq").hidden) return;
      const f = [...(e.clipboardData?.files || [])][0];
      if (f) upload(f);
    });

    $("mcqFilters").querySelectorAll(".segment").forEach((b) => {
      b.onclick = () => {
        M.filter = b.dataset.filter;
        $("mcqFilters").querySelectorAll(".segment").forEach((x) => {
          x.classList.toggle("active", x === b);
          x.setAttribute("aria-selected", String(x === b));
        });
        renderList();
      };
    });
    $("mcqSearch").oninput = (e) => {
      M.search = e.target.value;
      renderList();
    };

    $("mcqEditName").onclick = () => {
      if (!M.ds || !M.jobId) return;
      const input = $("mcqNameInput");
      input.value = M.ds.manifest?.name || "";
      input.dataset.original = input.value;
      input.hidden = false;
      $("mcqTitle").hidden = true;
      $("mcqEditName").hidden = true;
      input.focus(); input.select();
    };
    $("mcqNameInput").onkeydown = (e) => {
      if (e.key === "Enter") { e.preventDefault(); commitDatasetName(); }
      if (e.key === "Escape") {
        e.preventDefault();
        $("mcqNameInput").value = $("mcqNameInput").dataset.original || "";
        commitDatasetName();
      }
    };
    $("mcqNameInput").onblur = commitDatasetName;

    $("mcqDlZip").onclick = () => download("zip");
    $("mcqRebuild").onclick = async () => {
      if (!M.jobId) return;
      const body = { job_id: M.jobId,
                     answer_mode: $("mcqAnswerMode").value,
                     ai_mode: $("mcqAiMode").value };
      if (body.ai_mode !== "heuristic") {
        body.ai_provider = currentProvider()?.id || $("mcqProvider").value;
        body.ai_model = $("mcqModel").value.trim();
        if (!body.ai_model) {
          toastMsg("Choose or type a model first", "err");
          return;
        }
      }
      try {
        toastMsg("Rebuilding dataset…", "info", 1600);
        await mApi("/api/mcq/build", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        await loadJob(M.jobId);
        toastMsg("Dataset rebuilt", "ok");
      } catch (e) {
        toastMsg(`Rebuild failed: ${e.message}`, "err");
      }
    };
    document.querySelectorAll(".mcq-fmt button").forEach((b) => {
      b.onclick = () => download(b.dataset.fmt);
    });

    let saved = "text";
    try { saved = localStorage.getItem("ocr-view") || "text"; } catch (_) {}
    if (location.hash === "#mcq") saved = "mcq";
    showView(saved);
    refreshHistory();
  }

  document.addEventListener("DOMContentLoaded", init);

  // Hook used by the "Extract text" history rows to open a built dataset.
  window.mcqShow = (jid) => {
    showView("mcq");
    if (jid) loadJob(jid);
    else refreshHistory();
  };
})();
