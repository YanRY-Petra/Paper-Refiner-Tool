/* global fetch, document, localStorage */

const LS_SESSION_KEY = "paper_refiner_session_id";

let sessionId = null;
/** 单次「生成改写」最多勾选段数（与后端 PAPER_REFINER_MAX_BATCH 一致，默认 1000） */
let maxSelection = 1000;
/** @type {Array<Record<string, unknown>>} */
let lastParagraphs = [];
/** @type {Set<number>} */
let savedSelectedIndices = new Set();
let saveSelectionTimer = null;

async function readApiError(response) {
  const raw = await response.text();
  try {
    const j = JSON.parse(raw);
    const d = j.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((x) => {
          if (typeof x === "object" && x != null && "msg" in x) return String(x.msg);
          return JSON.stringify(x);
        })
        .join("; ");
    }
    if (d != null) return JSON.stringify(d);
    return raw || response.statusText;
  } catch (_) {
    return raw || response.statusText || `HTTP ${response.status}`;
  }
}

function persistSessionId(id) {
  if (id) localStorage.setItem(LS_SESSION_KEY, id);
}

function clearPersistedSession() {
  localStorage.removeItem(LS_SESSION_KEY);
}

async function loadConfig() {
  const r = await fetch("/api/config");
  if (r.ok) {
    const d = await r.json();
    maxSelection = d.max_refine_selection || 1000;
    const mo = document.getElementById("model-override");
    if (mo && !mo.value && d.default_model) {
      mo.placeholder = `默认: ${d.default_model}`;
    }
    updateSelectionUsage();
  }
}

/** 用量：已勾选段数 / 单次生成上限（占用本批次额度） */
function updateSelectionUsage() {
  const el = document.getElementById("selection-usage");
  if (!el) return;
  const n = savedSelectedIndices.size;
  const eligibleTotal = lastParagraphs.filter((p) => !p.skip_reason).length;
  el.textContent = `${n}/${maxSelection}`;
  const docHint =
    eligibleTotal > 0 ? `本稿共 ${eligibleTotal} 段可改写。` : "";
  el.title = `${docHint}已勾选 ${n} 段，占用单次「生成改写」额度；单次最多 ${maxSelection} 段（环境变量 PAPER_REFINER_MAX_BATCH）。`;
}

async function loadPrompts() {
  const sel = document.getElementById("prompt-select");
  sel.innerHTML = "";
  const r = await fetch("/api/prompts");
  if (!r.ok) return;
  const { prompts } = await r.json();
  for (const p of prompts) {
    const o = document.createElement("option");
    o.value = p.id;
    o.textContent = `${p.name} (${p.id})`;
    sel.appendChild(o);
  }
}

function applyRefineOptions(opts) {
  if (!opts) return;
  const sel = document.getElementById("prompt-select");
  if (opts.prompt_id && sel) {
    const has = Array.from(sel.options).some((o) => o.value === opts.prompt_id);
    if (has) sel.value = opts.prompt_id;
  }
  if (opts.temperature != null) {
    document.getElementById("temperature").value = String(opts.temperature);
  }
  const mo = document.getElementById("model-override");
  if (mo && opts.model) mo.value = opts.model;
}

function applySessionData(data, { restored = false } = {}) {
  sessionId = data.session_id;
  lastParagraphs = data.paragraphs || [];
  savedSelectedIndices = new Set(data.selected_indices || []);
  document.getElementById("file-name").textContent = data.original_filename || "";
  applyRefineOptions(data.refine_options || {});
  renderParagraphTable();
  setVisible("pick-section", true);
  showError(document.getElementById("refine-error"), "");
  showError(document.getElementById("export-error"), "");
  if (data.last_results && data.last_results.length) {
    renderResults(data.last_results);
    setVisible("review-section", true);
  } else {
    setVisible("review-section", false);
    document.getElementById("results").innerHTML = "";
  }
  persistSessionId(sessionId);
  updateRestoreHint(data, restored);
}

function updateRestoreHint(data, restored) {
  const el = document.getElementById("restore-hint");
  if (!el) return;
  if (!restored || !data.session_id) {
    el.textContent = "";
    el.hidden = true;
    return;
  }
  const name = data.original_filename || "document.docx";
  const n = (data.selected_indices || []).length;
  const selBit = n > 0 ? `，已勾选 ${n} 段` : "";
  const resBit =
    data.last_results && data.last_results.length
      ? `，含 ${data.last_results.length} 段改写结果`
      : "";
  el.textContent = `已自动恢复上次会话（未重新上传）：${name}${selBit}${resBit}。若要换文档，请点下方「重新上传」。`;
  el.hidden = false;
}

async function saveSelectionNow() {
  if (!sessionId) return;
  const body = {
    indices: Array.from(savedSelectedIndices).sort((a, b) => a - b),
    prompt_id: document.getElementById("prompt-select").value,
    temperature: parseFloat(document.getElementById("temperature").value) || 0.7,
    model: document.getElementById("model-override").value.trim() || null,
  };
  try {
    await fetch(`/api/session/${sessionId}/selection`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (_) {
    /* 静默失败，不影响主流程 */
  }
}

function scheduleSaveSelection() {
  if (saveSelectionTimer) clearTimeout(saveSelectionTimer);
  saveSelectionTimer = setTimeout(() => {
    saveSelectionTimer = null;
    saveSelectionNow();
  }, 400);
}

async function restoreSessionOnLoad() {
  const sid = localStorage.getItem(LS_SESSION_KEY);
  if (!sid) return;
  try {
    const r = await fetch(`/api/session/${sid}`);
    if (!r.ok) {
      clearPersistedSession();
      return;
    }
    const data = await r.json();
    applySessionData(data, { restored: true });
  } catch (_) {
    /* ignore */
  }
}

function showError(el, msg) {
  if (!el) return;
  if (msg) {
    el.textContent = msg;
    el.hidden = false;
  } else {
    el.textContent = "";
    el.hidden = true;
  }
}

function setVisible(id, on) {
  document.getElementById(id).classList.toggle("hidden", !on);
}

document.getElementById("file-input").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  const nameEl = document.getElementById("file-name");
  const err = document.getElementById("upload-error");
  showError(err, "");
  if (!file) {
    nameEl.textContent = "";
    return;
  }
  nameEl.textContent = file.name;
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/upload", { method: "POST", body: fd });
  if (!r.ok) {
    showError(err, await readApiError(r));
    return;
  }
  const data = await r.json();
  applySessionData(data, { restored: false });
});

function getEligibleIndicesSorted() {
  return lastParagraphs
    .filter((p) => !p.skip_reason)
    .map((p) => p.index)
    .sort((a, b) => a - b);
}

function selectAllEligible() {
  showError(document.getElementById("refine-error"), "");
  const eligibleSorted = getEligibleIndicesSorted();
  if (eligibleSorted.length === 0) return;
  const take = eligibleSorted.slice(0, maxSelection);
  savedSelectedIndices = new Set(take);
  renderParagraphTable();
  scheduleSaveSelection();
}

function selectNone() {
  showError(document.getElementById("refine-error"), "");
  savedSelectedIndices.clear();
  renderParagraphTable();
  scheduleSaveSelection();
}

function renderParagraphTable() {
  const tb = document.querySelector("#para-table tbody");
  tb.innerHTML = "";
  const onlyOk = document.getElementById("filter-eligible")?.checked;
  const rows = onlyOk ? lastParagraphs.filter((p) => !p.skip_reason) : lastParagraphs;

  for (const p of rows) {
    const tr = document.createElement("tr");
    const ok = !p.skip_reason;
    tr.className = ok ? "ok" : "skip";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.index = String(p.index);
    cb.disabled = !ok;
    cb.checked = ok && savedSelectedIndices.has(p.index);
    if (ok) {
      cb.addEventListener("change", (e) => {
        const idx = parseInt(e.target.dataset.index, 10);
        if (e.target.checked) {
          if (!savedSelectedIndices.has(idx) && savedSelectedIndices.size >= maxSelection) {
            e.target.checked = false;
            showError(
              document.getElementById("refine-error"),
              `单次最多勾选 ${maxSelection} 段（可由服务器环境变量 PAPER_REFINER_MAX_BATCH 调整）`
            );
            return;
          }
          savedSelectedIndices.add(idx);
        } else {
          savedSelectedIndices.delete(idx);
        }
        updateSelectionUsage();
        scheduleSaveSelection();
      });
    }
    const td0 = document.createElement("td");
    td0.appendChild(cb);
    const td1 = document.createElement("td");
    td1.textContent = p.index;
    const td2 = document.createElement("td");
    td2.textContent = ok ? "可改写" : p.skip_reason;
    const td3 = document.createElement("td");
    td3.textContent = p.style || "—";
    const td4 = document.createElement("td");
    const bodyEl = document.createElement("div");
    bodyEl.className = "full-text-cell";
    bodyEl.textContent = p.full_text != null ? String(p.full_text) : "";
    td4.appendChild(bodyEl);
    tr.append(td0, td1, td2, td3, td4);
    tb.appendChild(tr);
  }
  updateSelectionUsage();
}

const filterEl = document.getElementById("filter-eligible");
if (filterEl) {
  filterEl.addEventListener("change", () => renderParagraphTable());
}

document.getElementById("btn-select-all-eligible")?.addEventListener("click", selectAllEligible);
document.getElementById("btn-select-none")?.addEventListener("click", selectNone);

for (const id of ["prompt-select", "temperature", "model-override"]) {
  const el = document.getElementById(id);
  if (el) el.addEventListener("change", () => scheduleSaveSelection());
  if (el && id === "model-override") {
    el.addEventListener("input", () => scheduleSaveSelection());
  }
}

function getSelectedIndices() {
  return Array.from(savedSelectedIndices).sort((a, b) => a - b);
}

document.getElementById("btn-refine").addEventListener("click", async () => {
  const err = document.getElementById("refine-error");
  showError(err, "");
  if (!sessionId) {
    showError(err, "请先上传文件");
    return;
  }
  const indices = getSelectedIndices();
  if (indices.length === 0) {
    showError(err, "请至少勾选一段可改写段落");
    return;
  }
  if (indices.length > maxSelection) {
    showError(err, `单次最多勾选 ${maxSelection} 段（可在服务器设置环境变量 PAPER_REFINER_MAX_BATCH 调整）`);
    return;
  }
  const prompt_id = document.getElementById("prompt-select").value;
  const temperature = parseFloat(document.getElementById("temperature").value) || 0.7;
  const modelRaw = document.getElementById("model-override").value.trim();
  const body = {
    indices,
    prompt_id,
    temperature,
    model: modelRaw || null,
  };
  const btn = document.getElementById("btn-refine");
  btn.disabled = true;
  btn.textContent = `生成中…（共 ${indices.length} 段，逐段请求 LLM，请稍候）`;
  await saveSelectionNow();
  try {
    const r = await fetch(`/api/session/${sessionId}/refine`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      showError(err, await readApiError(r));
      return;
    }
    const data = await r.json();
    renderResults(data.results);
    setVisible("review-section", true);
  } finally {
    btn.disabled = false;
    btn.textContent = "生成改写";
  }
});

function renderResults(results) {
  const root = document.getElementById("results");
  root.innerHTML = "";
  const sorted = [...results].sort((a, b) => a.index - b.index);
  for (const item of sorted) {
    const block = document.createElement("div");
    block.className = "result-block";
    block.dataset.index = String(item.index);
    const h = document.createElement("h3");
    const pname = item.prompt_name != null ? String(item.prompt_name) : "";
    const pid = item.prompt_id != null ? String(item.prompt_id) : "";
    const promptBit = pid ? ` · ${pname ? `${pname} (${pid})` : pid}` : "";
    h.textContent = `段落 #${item.index}${item.style ? ` · ${item.style}` : ""}${promptBit}`;
    const accept = document.createElement("label");
    accept.style.display = "flex";
    accept.style.alignItems = "center";
    accept.style.gap = "0.5rem";
    accept.style.marginBottom = "0.5rem";
    const acb = document.createElement("input");
    acb.type = "checkbox";
    acb.className = "accept-cb";
    acb.checked = true;
    accept.appendChild(acb);
    accept.appendChild(document.createTextNode("采纳本段（写入导出 docx）"));

    const grid = document.createElement("div");
    grid.className = "grid-two";
    const b1 = document.createElement("div");
    b1.innerHTML = "<strong>原文</strong>";
    const ta1 = document.createElement("textarea");
    ta1.readOnly = true;
    ta1.value = item.before || "";
    const b2 = document.createElement("div");
    b2.innerHTML = "<strong>改写稿（可编辑）</strong>";
    const ta2 = document.createElement("textarea");
    ta2.className = "after-text";
    ta2.value = item.after || "";

    grid.appendChild(b1);
    grid.appendChild(b2);
    grid.appendChild(ta1);
    grid.appendChild(ta2);
    block.append(h, accept, grid);
    root.appendChild(block);
  }
}

document.getElementById("btn-export").addEventListener("click", async () => {
  const err = document.getElementById("export-error");
  showError(err, "");
  if (!sessionId) {
    showError(err, "无会话");
    return;
  }
  const blocks = document.querySelectorAll(".result-block");
  const edits = [];
  for (const block of blocks) {
    const acb = block.querySelector(".accept-cb");
    if (!acb || !acb.checked) continue;
    const idx = parseInt(block.dataset.index, 10);
    const ta = block.querySelector(".after-text");
    edits.push({ index: idx, text: ta ? ta.value : "" });
  }
  if (edits.length === 0) {
    showError(err, "请至少采纳一段后再导出");
    return;
  }
  const btn = document.getElementById("btn-export");
  btn.disabled = true;
  btn.textContent = "导出中…";
  try {
    const r = await fetch(`/api/session/${sessionId}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ edits }),
    });
    if (!r.ok) {
      showError(err, await readApiError(r));
      return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "refined.docx";
    a.click();
    URL.revokeObjectURL(url);
  } finally {
    btn.disabled = false;
    btn.textContent = "导出已采纳段落为 docx";
  }
});

document.getElementById("btn-reset").addEventListener("click", async () => {
  if (sessionId) {
    try {
      await fetch(`/api/session/${sessionId}`, { method: "DELETE" });
    } catch (_) {
      /* ignore */
    }
  }
  sessionId = null;
  lastParagraphs = [];
  savedSelectedIndices = new Set();
  clearPersistedSession();
  const hint = document.getElementById("restore-hint");
  if (hint) {
    hint.textContent = "";
    hint.hidden = true;
  }
  document.getElementById("file-input").value = "";
  document.getElementById("file-name").textContent = "";
  setVisible("pick-section", false);
  setVisible("review-section", false);
  document.getElementById("results").innerHTML = "";
  updateSelectionUsage();
});

document.querySelector(".file-label .btn").addEventListener("click", (e) => {
  e.preventDefault();
  document.getElementById("file-input").click();
});

Promise.all([loadConfig(), loadPrompts()]).then(() => restoreSessionOnLoad());
