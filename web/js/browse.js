import { api } from "./api.js";
import { renderLatex, plainPreview } from "./render.js";
import { openWholeEditor, openMathPopup } from "./edit.js";

const state = {
  taxonomy: null,
  unit: null,
  topic: "",
  query: "",
  items: [],
  current: null,
  filters: { needs_review: false, untagged: false },
};

let els = {};

export function init(ctx) {
  els = {
    tree: document.getElementById("tree"),
    list: document.getElementById("qlist"),
    title: document.getElementById("list-title"),
    count: document.getElementById("list-count"),
    detail: document.getElementById("detail"),
    search: document.getElementById("search"),
    fReview: document.getElementById("f-review"),
    fUntagged: document.getElementById("f-untagged"),
  };
  state.onSelect = ctx.onSelect;

  els.detail.addEventListener("click", onDetailClick);

  els.search.addEventListener("input", debounce(() => {
    state.query = els.search.value.trim();
    reload();
  }, 220));
  els.fReview.addEventListener("change", () => {
    state.filters.needs_review = els.fReview.checked; reload();
  });
  els.fUntagged.addEventListener("change", () => {
    state.filters.untagged = els.fUntagged.checked; reload();
  });

  return refreshTree();
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export async function refreshTree() {
  state.taxonomy = await api.taxonomy();
  renderTree();
}

function renderTree() {
  const tax = state.taxonomy;
  els.tree.innerHTML = "";
  const all = document.createElement("button");
  all.className = "tree-unit-head";
  all.innerHTML = `<span class="caret">▸</span> All questions
                   <span class="tree-count">${tax.units.reduce((s, u) => s + (u.count || 0), 0)}</span>`;
  all.onclick = () => { state.unit = null; state.topic = ""; renderTree(); reload(); };
  els.tree.appendChild(all);

  for (const unit of tax.units) {
    const wrap = document.createElement("div");
    wrap.className = "tree-unit" + (state.unit === unit.id ? " open" : "");
    const head = document.createElement("button");
    head.className = "tree-unit-head";
    head.innerHTML = `<span class="caret">${state.unit === unit.id ? "▾" : "▸"}</span>
                      Unit ${unit.id} · ${unit.title}
                      <span class="tree-count">${unit.count || 0}</span>`;
    head.onclick = () => {
      state.unit = state.unit === unit.id ? null : unit.id;
      state.topic = "";
      renderTree();
      reload();
    };
    wrap.appendChild(head);

    const topics = document.createElement("div");
    topics.className = "tree-topics";
    for (const t of unit.topics) {
      const b = document.createElement("button");
      b.className = "tree-topic" + (state.topic === t.id ? " active" : "");
      b.innerHTML = `<span>${t.id} ${t.title}</span><span class="tree-count">${t.count || 0}</span>`;
      b.onclick = () => { state.unit = unit.id; state.topic = t.id; renderTree(); reload(); };
      topics.appendChild(b);
    }
    wrap.appendChild(topics);
    els.tree.appendChild(wrap);
  }
}

export async function reload() {
  const res = await api.questions({
    q: state.query,
    unit: state.unit ?? "",
    topic: state.topic,
    needs_review: state.filters.needs_review,
    untagged: state.filters.untagged,
    limit: 300,
  });
  state.items = res.questions;
  const label = state.topic ? `Unit ${state.unit} · ${state.topic}`
              : state.unit ? `Unit ${state.unit}`
              : state.query ? `Search: ${state.query}` : "All questions";
  els.title.textContent = label;
  els.count.textContent = `${res.total} question${res.total === 1 ? "" : "s"}`;
  renderList();
}

function renderList() {
  els.list.innerHTML = "";
  for (const q of state.items) {
    const card = document.createElement("div");
    card.className = "qcard" + (state.current && state.current.id === q.id ? " active" : "");
    const tags = [];
    if ((q.images || []).length) tags.push(`<span class="tag tag-fig">fig ×${q.images.length}</span>`);
    if (q.answer) tags.push(`<span class="tag tag-ans">${q.answer}</span>`);
    if (q.difficulty) tags.push(`<span class="tag">${q.difficulty}</span>`);
    if (q.needs_review) tags.push(`<span class="tag tag-review">review</span>`);
    card.innerHTML =
      `<div class="qcard-top">
         <span class="qcard-id">${q.id}</span>
         <span class="qcard-tags">${tags.join("")}</span>
       </div>
       <div class="qcard-body">${escapeBraces(plainPreview(q))}</div>`;
    card.onclick = () => select(q, card);
    els.list.appendChild(card);
  }
}

function escapeBraces(s) {
  return String(s).replace(/</g, "&lt;");
}

function select(q, card) {
  state.current = q;
  [...els.list.children].forEach(c => c.classList.remove("active"));
  if (card) card.classList.add("active");
  renderDetail(q);
}

function renderDetail(q) {
  const choices = (q.choices || []).map((c, ci) =>
    `<li><span class="choice-label">${c.label}</span><span>${renderLatex(c.text, "choice:" + ci)}</span></li>`).join("");
  const meta = [];
  if (q.topic) meta.push(`<span class="tag">${q.topic} ${q.topic_title || ""}</span>`);
  if (q.qtype) meta.push(`<span class="tag">${q.qtype}</span>`);
  if (q.source && q.source.doc) meta.push(`<span class="tag">${q.source.doc}` +
    (q.source.book_page ? ` p.${q.source.book_page}` : "") + `</span>`);

  els.detail.innerHTML = `
    <div class="qpaper">
      <div class="qpaper-head">
        <h3>Question ${q.number || ""}</h3>
        <span class="muted">${q.id}</span>
      </div>
      <div class="qstem">${renderLatex(q.stem, "stem")}</div>
      ${choices ? `<ul class="choices">${choices}</ul>` : ""}
      ${q.answer ? `<div class="answer-box"><strong>Answer:</strong> ${renderLatex(q.answer, "answer")}</div>` : ""}
      ${q.solution ? `<div class="solution-box"><strong>Solution.</strong> ${renderLatex(q.solution, "solution")}</div>` : ""}
      <div class="qmeta">${meta.join("")}</div>
      <div class="qactions">
        <button class="btn" data-act="add">Add to paper</button>
        <button class="btn btn-primary" data-act="edit">Edit LaTeX</button>
        <button class="btn" data-act="tex">View LaTeX</button>
        <button class="btn" data-act="toggle-review">${q.needs_review ? "Clear review flag" : "Flag for review"}</button>
      </div>
      <div id="tex-slot"></div>
    </div>`;

  els.detail.querySelector('[data-act="add"]').onclick = () => {
    state.onSelect(q);
    toast(`${q.id} added to the paper`);
  };
  els.detail.querySelector('[data-act="edit"]').onclick = () => {
    openWholeEditor(q, (parsed) => {
      q.stem = parsed.stem;
      q.choices = parsed.choices;
      q.answer = parsed.answer;
      q.solution = parsed.solution;
      renderDetail(q);
      reload();
    });
  };
  els.detail.querySelector('[data-act="toggle-review"]').onclick = async () => {
    await api.patch(q.id, { needs_review: !q.needs_review });
    q.needs_review = !q.needs_review;
    toast("updated");
    reload();
  };
  els.detail.querySelector('[data-act="tex"]').onclick = async () => {
    const slot = document.getElementById("tex-slot");
    if (slot.dataset.open === "1") { slot.innerHTML = ""; slot.dataset.open = "0"; return; }
    const tex = await api.questionTex(q.id);
    slot.innerHTML = `<pre class="texbox">${escapeBraces(tex)}</pre>`;
    slot.dataset.open = "1";
  };
}

/** PATCH one field and refresh the in-memory question + previews. */
async function commitField(field, value) {
  const q = state.current;
  await api.patch(q.id, { [field]: value });
  if (field === "choices") q.choices = value;
  else q[field] = value;
  renderDetail(q);
  reload();
}

/** Open the single-formula popover when a rendered formula is clicked. */
function onDetailClick(e) {
  const span = e.target.closest(".math");
  if (!span || !els.detail.contains(span)) return;
  const fieldKey = span.dataset.field || "";
  const idx = parseInt(span.dataset.idx || "0", 10);
  openMathPopup({
    q: state.current,
    fieldKey,
    idx,
    anchorEl: span,
    commit: commitField,
  });
}

export function currentContext() {
  return { unit: state.unit, topic: state.topic, items: state.items };
}

let toastTimer;
export function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
}
