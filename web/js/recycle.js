import { api } from "./api.js";
import { renderLatex } from "./render.js";
import { toast } from "./session.js";

// The recycle bin.  Deleting a question from the bank never destroys it: it
// lands here with a thirty-day clock, and can be restored or deleted for good.

let els = {};
let items = [];
let retentionDays = 30;
let current = null;

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

export function init() {
  els = {
    list: document.getElementById("r-list"),
    detail: document.getElementById("r-detail"),
    meta: document.getElementById("r-meta"),
    empty: document.getElementById("r-empty"),
  };
  if (els.empty) els.empty.onclick = emptyBin;
}

export async function refresh() {
  if (!els.list) return;
  try {
    const payload = await api.recycle();
    items = payload.items || [];
    retentionDays = payload.retention_days || 30;
    if (els.meta) {
      els.meta.textContent = items.length
        ? `${items.length} question${items.length === 1 ? "" : "s"} · kept for ${retentionDays} days`
        : `Nothing here. Deleted questions are kept ${retentionDays} days.`;
    }
    renderList();
  } catch (err) {
    if (els.meta) els.meta.textContent = String(err.message || err);
  }
}

function renderList() {
  els.list.innerHTML = items.map(item => `
    <div class="qcard${current && current.id === item.id ? " active" : ""}"
         data-id="${escapeHtml(item.id)}">
      <div class="qcard-top">
        <span class="qcard-id">${escapeHtml(item.id)}</span>
        <span class="qcard-tags">
          <span class="tag tag-review">${item.days_left} day${item.days_left === 1 ? "" : "s"} left</span>
        </span>
      </div>
      <div class="qcard-body">${escapeHtml(item.preview || "")}</div>
    </div>`).join("") || `<p class="muted small">The recycle bin is empty.</p>`;

  els.list.querySelectorAll(".qcard").forEach(card => {
    card.onclick = () => {
      current = items.find(i => i.id === card.dataset.id);
      renderList();
      renderDetail();
    };
  });
}

function renderDetail() {
  if (!current) {
    els.detail.innerHTML = `<div class="empty"><p>Select a deleted question.</p></div>`;
    return;
  }
  const q = current.question || {};
  const blocks = (q.stem_blocks || []).filter(b => b.type === "image").length;
  els.detail.innerHTML = `
    <div class="qpaper">
      <div class="qpaper-head">
        <h3>${escapeHtml(current.id)}</h3>
        <span class="muted">deleted ${escapeHtml(current.deleted_at || "")}
          ${current.deleted_by_name ? "by " + escapeHtml(current.deleted_by_name) : ""}</span>
      </div>
      <div class="qstem">${renderLatex(q.stem)}</div>
      ${(q.choices || []).length ? `<ul class="choices">${q.choices.map(c =>
        `<li><span class="choice-label">${escapeHtml(c.label)}</span>
             <span>${renderLatex(c.text)}</span></li>`).join("")}</ul>` : ""}
      <div class="qmeta">
        <span class="tag">${escapeHtml(current.topic || "")} ${escapeHtml(current.topic_title || "")}</span>
        ${(current.additional_topics || []).map(t =>
          `<span class="tag tag-extra">+${escapeHtml(t)}</span>`).join("")}
        ${blocks ? `<span class="tag">${blocks} figure block(s)</span>` : ""}
        <span class="tag tag-review">permanent in ${current.days_left} day(s)</span>
      </div>
      <div class="qactions">
        <button class="btn btn-primary" data-act="restore">Restore</button>
        <button class="btn danger" data-act="purge">Delete permanently</button>
      </div>
    </div>`;

  els.detail.querySelector('[data-act="restore"]').onclick = async () => {
    await api.recycleRestore(current.id);
    toast(`${current.id} restored`);
    current = null;
    await refresh();
    renderDetail();
  };
  els.detail.querySelector('[data-act="purge"]').onclick = async () => {
    if (!confirm(`Delete ${current.id} permanently? This cannot be undone.`)) return;
    await api.recyclePurge(current.id);
    toast(`${current.id} deleted permanently`);
    current = null;
    await refresh();
    renderDetail();
  };
}

async function emptyBin() {
  if (!items.length) return;
  if (!confirm(`Delete all ${items.length} question(s) permanently?`)) return;
  const res = await api.recycleEmpty();
  toast(`${res.removed} question(s) deleted permanently`);
  current = null;
  await refresh();
  renderDetail();
}
