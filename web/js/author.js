import { api } from "./api.js";
import { renderLatex } from "./render.js";
import * as courses from "./courses.js";
import { toast } from "./session.js";

// New question: build the stem out of blocks.
//
// The blocks are the editable form; the LaTeX stem the paper uses is derived
// from them.  An image block with nothing in it yet renders as a placeholder, so
// a half-finished question looks half-finished rather than silently missing a
// figure.

const PLACEHOLDER = "media/placeholder.png";

let els = {};
let blocks = [];
let choices = [];
let picker = null;
let editingId = null;

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

export function init() {
  els = {
    blocks: document.getElementById("a-blocks"),
    choices: document.getElementById("a-choices"),
    topics: document.getElementById("a-topics"),
    status: document.getElementById("a-status"),
    title: document.getElementById("a-title"),
    answer: document.getElementById("a-answer"),
    solution: document.getElementById("a-solution"),
    save: document.getElementById("a-save"),
    reset: document.getElementById("a-reset"),
    addBlock: document.getElementById("a-add-text"),
    addImage: document.getElementById("a-add-image"),
    preview: document.getElementById("a-preview"),
  };
  if (!els.save) return;

  els.save.onclick = save;
  els.reset.onclick = () => resetForm();
  els.addBlock.onclick = () => { blocks.push({ type: "text", text: "" }); renderBlocks(); };
  els.addImage.onclick = () => {
    blocks.push({ type: "image", path: "", width: 0.5, caption: "" });
    renderBlocks();
  };

  resetForm();
}

export function resetForm() {
  editingId = null;
  blocks = [{ type: "text", text: "" }];
  choices = ["A", "B", "C", "D"].map(label => ({ label, text: "" }));
  if (els.title) els.title.textContent = "New question";
  if (els.answer) els.answer.value = "";
  if (els.solution) els.solution.value = "";
  setStatus("");
  renderBlocks();
  renderChoices();
  void renderTopics();
}

/** Load an existing question into the editor. */
export async function edit(id) {
  const question = await api.question(id);
  editingId = id;
  blocks = (question.stem_blocks && question.stem_blocks.length)
    ? question.stem_blocks.map(b => ({ ...b }))
    : [{ type: "text", text: question.stem || "" }];
  choices = (question.choices || []).length
    ? question.choices.map(c => ({ ...c }))
    : ["A", "B", "C", "D"].map(label => ({ label, text: "" }));
  if (els.title) els.title.textContent = `Editing ${id}`;
  if (els.answer) els.answer.value = question.answer || "";
  if (els.solution) els.solution.value = question.solution || "";
  renderBlocks();
  renderChoices();
  await renderTopics(question.topic, question.additional_topics || []);
  setStatus("");
}

async function renderTopics(primary = "", additional = []) {
  const taxonomy = await courses.taxonomy();
  picker = courses.renderTopicPicker(els.topics, taxonomy, {
    primary: primary || picker?.primaryId() || "",
    selected: primary ? [primary, ...additional] : picker?.values() || [],
  });
}

// --------------------------------------------------------------------------------------
// blocks
// --------------------------------------------------------------------------------------

function blocksToLatex(list) {
  return list.map(block => {
    if (block.type === "text") return (block.text || "").trim();
    const path = (block.path || "").trim() || PLACEHOLDER;
    const width = (block.width || 0.5).toFixed(2);
    const figure = `\\includegraphics[width=${width}\\linewidth]{${path}}`;
    return block.caption ? figure + "\n\n" + block.caption : figure;
  }).filter(Boolean).join("\n\n");
}

function renderBlocks() {
  els.blocks.innerHTML = blocks.map((block, index) => {
    const move = `
      <button class="icon-btn" data-move="${index}" data-dir="-1"
        ${index === 0 ? "disabled" : ""} title="move up">↑</button>
      <button class="icon-btn" data-move="${index}" data-dir="1"
        ${index === blocks.length - 1 ? "disabled" : ""} title="move down">↓</button>
      <button class="icon-btn danger" data-remove="${index}" title="remove">×</button>`;

    if (block.type === "text") {
      return `
        <div class="block block-text">
          <div class="block-head"><span class="block-kind">text</span>${move}</div>
          <textarea class="input block-input" rows="3" data-text="${index}"
            placeholder="LaTeX, e.g. A block of mass $m$ slides down a ramp...">${escapeHtml(block.text || "")}</textarea>
        </div>`;
    }
    const src = block.path ? "/api/file?path=" + encodeURIComponent(block.path) : "";
    return `
      <div class="block block-image">
        <div class="block-head"><span class="block-kind">image</span>${move}</div>
        <div class="block-image-body">
          <div class="block-thumb${block.path ? "" : " empty"}">
            ${block.path
              ? `<img src="${src}" alt="" />`
              : `<span class="block-thumb-hint">placeholder</span>`}
          </div>
          <div class="block-image-fields">
            <input type="file" accept="image/*" data-upload="${index}" />
            <label class="lbl">width (fraction of the line)</label>
            <input class="input" type="number" min="0.1" max="1" step="0.05"
                   value="${block.width || 0.5}" data-width="${index}" />
            <input class="input" placeholder="caption (optional)"
                   value="${escapeHtml(block.caption || "")}" data-caption="${index}" />
            ${block.path ? `<button class="btn btn-ghost" data-clear="${index}">clear image</button>` : ""}
          </div>
        </div>
      </div>`;
  }).join("") || `<p class="muted small">Add a text or image block to start.</p>`;

  els.blocks.querySelectorAll("[data-text]").forEach(textarea => {
    textarea.oninput = () => {
      blocks[Number(textarea.dataset.text)].text = textarea.value;
      renderPreview();
    };
  });
  els.blocks.querySelectorAll("[data-move]").forEach(button => {
    button.onclick = () => {
      const index = Number(button.dataset.move);
      const target = index + Number(button.dataset.dir);
      if (target < 0 || target >= blocks.length) return;
      const [moved] = blocks.splice(index, 1);
      blocks.splice(target, 0, moved);
      renderBlocks();
    };
  });
  els.blocks.querySelectorAll("[data-remove]").forEach(button => {
    button.onclick = () => {
      blocks.splice(Number(button.dataset.remove), 1);
      renderBlocks();
    };
  });
  els.blocks.querySelectorAll("[data-width]").forEach(input => {
    input.onchange = () => {
      blocks[Number(input.dataset.width)].width = Number(input.value) || 0.5;
      renderPreview();
    };
  });
  els.blocks.querySelectorAll("[data-caption]").forEach(input => {
    input.onchange = () => {
      blocks[Number(input.dataset.caption)].caption = input.value;
      renderPreview();
    };
  });
  els.blocks.querySelectorAll("[data-clear]").forEach(button => {
    button.onclick = () => {
      const block = blocks[Number(button.dataset.clear)];
      block.path = "";
      renderBlocks();
    };
  });
  els.blocks.querySelectorAll("[data-upload]").forEach(input => {
    input.onchange = async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      try {
        const res = await api.uploadImage(file);
        const block = blocks[Number(input.dataset.upload)];
        block.path = res.path;
        renderBlocks();
        toast("Figure uploaded");
      } catch (err) {
        setStatus(String(err.message || err), true);
      }
    };
  });

  renderPreview();
}

function renderPreview() {
  if (!els.preview) return;
  const latex = blocksToLatex(blocks);
  els.preview.innerHTML = `
    <div class="qpaper">
      <div class="qstem">${renderLatex(latex) || "<span class='muted'>Nothing yet.</span>"}</div>
      <details class="author-latex">
        <summary>Derived stem LaTeX</summary>
        <pre class="texbox">${escapeHtml(latex)}</pre>
      </details>
    </div>`;
}

// --------------------------------------------------------------------------------------
// choices
// --------------------------------------------------------------------------------------

function renderChoices() {
  els.choices.innerHTML = choices.map((choice, index) => `
    <div class="choice-row">
      <span class="choice-label">${escapeHtml(choice.label)}</span>
      <input class="input" value="${escapeHtml(choice.text || "")}"
             data-choice="${index}" placeholder="option ${escapeHtml(choice.label)}" />
      <button class="icon-btn danger" data-choice-remove="${index}" title="remove">×</button>
    </div>`).join("") +
    `<button class="btn btn-ghost" id="a-choice-add">Add option</button>`;

  els.choices.querySelectorAll("[data-choice]").forEach(input => {
    input.oninput = () => { choices[Number(input.dataset.choice)].text = input.value; };
  });
  els.choices.querySelectorAll("[data-choice-remove]").forEach(button => {
    button.onclick = () => {
      choices.splice(Number(button.dataset.choiceRemove), 1);
      renderChoices();
    };
  });
  const add = document.getElementById("a-choice-add");
  if (add) {
    add.onclick = () => {
      const label = String.fromCharCode(65 + choices.length);
      choices.push({ label, text: "" });
      renderChoices();
    };
  }
}

// --------------------------------------------------------------------------------------
// save
// --------------------------------------------------------------------------------------

function setStatus(message, isError = false) {
  if (!els.status) return;
  els.status.textContent = message || "";
  els.status.className = "status" + (isError ? " err" : " ok");
}

async function save() {
  const topic = picker ? picker.primaryId() : "";
  if (!topic) {
    setStatus("Choose at least one knowledge block.", true);
    return;
  }
  const payload = {
    id: editingId || null,
    topic,
    additional_topics: picker.additional(),
    stem_blocks: blocks,
    choices: choices.map(c => ({ label: c.label, text: c.text })),
    answer: els.answer.value.trim(),
    solution: els.solution.value,
    qtype: "mcq",
  };
  try {
    const res = await api.author(payload);
    toast(res.created ? `Created ${res.question.id}` : `Updated ${res.question.id}`);
    setStatus(`Saved ${res.question.id}.`);
    window.dispatchEvent(new CustomEvent("bank:changed"));
    if (res.created) {
      editingId = res.question.id;
      if (els.title) els.title.textContent = `Editing ${res.question.id}`;
    }
  } catch (err) {
    setStatus(String(err.message || err).replace(/^\d+\s*/, ""), true);
  }
}
