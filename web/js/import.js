import { api } from "./api.js";
import { renderLatex, plainPreview } from "./render.js";

const state = { jobs: [], job: null, questions: [] };
let els = {};

export function init(ctx) {
  els = {
    file: document.getElementById("i-file"),
    docid: document.getElementById("i-docid"),
    dpi: document.getElementById("i-dpi"),
    upload: document.getElementById("i-upload"),
    jobs: document.getElementById("i-jobs"),
    list: document.getElementById("i-list"),
    title: document.getElementById("i-title"),
    actions: document.getElementById("i-actions"),
    polish: document.getElementById("i-polish"),
    commit: document.getElementById("i-commit"),
    status: document.getElementById("i-status"),
    preview: document.getElementById("i-preview"),
  };
  ctx.onCommitted = () => {};

  els.upload.onclick = upload;
  els.polish.onclick = polish;
  els.commit.onclick = commit;
  refreshJobs();
}

function setStatus(msg, isError = false) {
  els.status.textContent = msg;
  els.status.className = "status" + (isError ? " err" : " ok");
}

async function upload() {
  if (!els.file.files.length) { setStatus("Choose a PDF first.", true); return; }
  setStatus("Extracting — figures are rendered at " + els.dpi.value + " DPI…");
  try {
    const meta = await api.ingestUpload(els.file.files[0], els.docid.value.trim(), +els.dpi.value);
    setStatus(`${meta.count} questions extracted as ${meta.job}.`);
    await refreshJobs();
    openJob(meta.job);
  } catch (err) {
    setStatus(String(err.message || err), true);
  }
}

export async function refreshJobs() {
  const res = await api.ingestJobs();
  state.jobs = res.jobs;
  els.jobs.innerHTML = "";
  for (const j of res.jobs.slice().reverse()) {
    const d = document.createElement("div");
    d.className = "job" + (state.job === j.job ? " active" : "");
    d.innerHTML = `<div class="job-title">${j.doc_id} · ${j.count} Q</div>
                   <div class="job-meta">${j.filename} · ${j.created} · ${j.stage}</div>`;
    d.onclick = () => openJob(j.job);
    els.jobs.appendChild(d);
  }
}

export async function openJob(job) {
  state.job = job;
  const res = await api.ingestJob(job);
  state.questions = res.questions;
  els.title.textContent = `${res.meta.doc_id} — ${res.meta.count} questions`;
  els.actions.style.display = "flex";
  renderList();
  refreshJobs();
}

function renderList() {
  els.list.innerHTML = "";
  state.questions.forEach((q, i) => {
    const card = document.createElement("div");
    card.className = "qcard";
    card.innerHTML =
      `<div class="qcard-top">
         <span class="qcard-id">${i + 1}. ${q.id}</span>
         <span class="qcard-tags">
           ${(q.images || []).length ? `<span class="tag tag-fig">fig ×${q.images.length}</span>` : ""}
           ${q.needs_review ? `<span class="tag tag-review">review</span>` : ""}
           ${q.ai_polished ? `<span class="tag tag-ans">ai</span>` : ""}
         </span>
       </div>
       <div class="qcard-body">${plainPreview(q, 140).replace(/</g, "&lt;")}</div>`;
    card.onclick = () => preview(q);
    els.list.appendChild(card);
  });
}

function preview(q) {
  const choices = (q.choices || []).map(c =>
    `<li><span class="choice-label">${c.label}</span><span>${renderLatex(c.text)}</span></li>`).join("");
  els.preview.innerHTML = `
    <div class="qpaper">
      <div class="qpaper-head"><h3>${q.id}</h3><span class="muted">${q.topic || ""} ${q.topic_title || ""}</span></div>
      <div class="qstem">${renderLatex(q.stem)}</div>
      ${choices ? `<ul class="choices">${choices}</ul>` : ""}
      <div class="qactions">
        <button class="btn" data-act="tex">View LaTeX</button>
      </div>
      <div id="i-tex-slot"></div>
    </div>`;
  els.preview.querySelector('[data-act="tex"]').onclick = () => {
    const slot = document.getElementById("i-tex-slot");
    if (slot.dataset.open === "1") { slot.innerHTML = ""; slot.dataset.open = "0"; return; }
    const body = [q.stem, ...(q.choices || []).map(c => `(${c.label}) ${c.text}`)].join("\n\n");
    slot.innerHTML = `<pre class="texbox">${body.replace(/</g, "&lt;")}</pre>`;
    slot.dataset.open = "1";
  };
}

async function polish() {
  if (!state.job) return;
  setStatus("Polishing with the configured model…");
  try {
    const res = await api.ingestPolish(state.job);
    await openJob(state.job);
    setStatus(`Polished ${res.count} questions.`);
  } catch (err) {
    setStatus(String(err.message || err), true);
  }
}

async function commit() {
  if (!state.job) return;
  setStatus("Committing to the bank…");
  try {
    const res = await api.ingestCommit(state.job);
    setStatus(`Committed ${res.count} questions, ${res.figures} figures.`);
    await refreshJobs();
    window.dispatchEvent(new CustomEvent("bank:changed"));
  } catch (err) {
    setStatus(String(err.message || err), true);
  }
}
