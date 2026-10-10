import { api } from "./api.js";
import { renderLatex, plainPreview } from "./render.js";

const selection = [];   // ordered list of question objects

let els = {};

export function init(ctx) {
  els = {
    list: document.getElementById("c-list"),
    count: document.getElementById("c-count"),
    preview: document.getElementById("c-preview"),
    instructions: document.getElementById("c-instructions"),
    answers: document.getElementById("c-answers"),
    solutions: document.getElementById("c-solutions"),
    group: document.getElementById("c-group"),
    filename: document.getElementById("c-filename"),
    status: document.getElementById("c-status"),
  };
  ctx.getBrowseContext = ctx.getBrowseContext || (() => ({}));

  document.getElementById("c-tex").onclick = () => download(false);
  document.getElementById("c-pdf").onclick = () => download(true);
  document.getElementById("c-clear").onclick = () => { selection.length = 0; render(); };
  document.getElementById("c-addtopic").onclick = addCurrentTopic;

  render();
}

export function add(q) {
  if (selection.some(x => x.id === q.id)) return false;
  selection.push(q);
  render();
  return true;
}

async function addCurrentTopic() {
  const ctx = window.__browseContext || {};
  if (!ctx.topic) { setStatus("Pick a topic in Browse first.", true); return; }
  const res = await api.questions({ topic: ctx.topic, limit: 300 });
  let n = 0;
  for (const q of res.questions) if (add(q)) n++;
  setStatus(`Added ${n} question(s) from ${ctx.topic}.`);
}

function options() {
  return {
    ids: selection.map(q => q.id),
    instructions: els.instructions.value || "",
    show_answer: els.answers.checked,
    show_solution: els.solutions.checked,
    group_by_topic: els.group.checked,
    filename: (els.filename.value || "practice-set").replace(/[^\w.-]+/g, "_"),
  };
}

async function download(asPdf) {
  if (!selection.length) { setStatus("Nothing selected.", true); return; }
  const opts = options();
  setStatus(asPdf ? "Compiling — this can take a minute…" : "Building LaTeX…");
  try {
    if (asPdf) {
      await api.exportPdf(opts, opts.filename + ".pdf");
      setStatus("PDF downloaded.");
    } else {
      const res = await api.exportTex(opts);
      const blob = new Blob([res.tex], { type: "application/x-tex" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = opts.filename + ".tex"; a.click();
      URL.revokeObjectURL(url);
      setStatus(`LaTeX exported (${res.count} questions).`);
    }
  } catch (err) {
    setStatus(String(err.message || err), true);
  }
}

function setStatus(msg, isError = false) {
  els.status.textContent = msg;
  els.status.className = "status" + (isError ? " err" : " ok");
}

function render() {
  els.count.textContent = selection.length;
  els.list.innerHTML = "";
  selection.forEach((q, i) => {
    const card = document.createElement("div");
    card.className = "qcard" + (selection.__current === q.id ? " active" : "");
    card.draggable = true;
    card.innerHTML =
      `<button class="qcard-remove" title="remove">×</button>
       <div class="qcard-top">
         <span class="qcard-id">${i + 1}. ${q.id}</span>
         <span class="qcard-tags"><span class="tag">${q.topic || ""}</span></span>
       </div>
       <div class="qcard-body">${plainPreview(q, 120).replace(/</g, "&lt;")}</div>`;
    card.querySelector(".qcard-remove").onclick = (e) => {
      e.stopPropagation();
      selection.splice(i, 1);
      render();
    };
    card.onclick = () => { selection.__current = q.id; render(); preview(q); };
    card.ondragstart = (e) => { e.dataTransfer.setData("text/plain", String(i)); };
    card.ondragover = (e) => { e.preventDefault(); };
    card.ondrop = (e) => {
      e.preventDefault();
      const from = parseInt(e.dataTransfer.getData("text/plain"), 10);
      if (isNaN(from) || from === i) return;
      const [moved] = selection.splice(from, 1);
      selection.splice(i, 0, moved);
      render();
    };
    els.list.appendChild(card);
  });
}

function preview(q) {
  const choices = (q.choices || []).map(c =>
    `<li><span class="choice-label">${c.label}</span><span>${renderLatex(c.text)}</span></li>`).join("");
  // the preview mirrors the printed page: the question itself, nothing else
  els.preview.innerHTML = `
    <div class="qpaper">
      <div class="qstem">${renderLatex(q.stem)}</div>
      ${choices ? `<ul class="choices">${choices}</ul>` : ""}
      ${q.answer ? `<div class="answer-box"><strong>Answer:</strong> ${q.answer}</div>` : ""}
      ${q.solution ? `<div class="solution-box"><strong>Solution.</strong> ${renderLatex(q.solution)}</div>` : ""}
    </div>`;
}

export function count() { return selection.length; }
