/* Two LaTeX editors:
 *   - openWholeEditor(q, onSaved): full-screen modal editing the whole question
 *     as one LaTeX source (STEM / CHOICES / ANSWER / SOLUTION sections). Save is
 *     required to leave; leaving with unsaved changes asks first.
 *   - openMathPopup({q, fieldKey, idx, anchorEl, commit}): a small floating
 *     popover for one formula / quantity. Edits apply on close; if the result
 *     cannot compile it is reverted automatically.
 */

import { api } from "./api.js";
import { replaceMathRun, extractMathRuns } from "./render.js";

const root = () => document.getElementById("edit-root");

function toast(msg) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}

function escAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;")
              .replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* ----------------------------------------------------------------------- *
 * Whole-question editor
 * ----------------------------------------------------------------------- */

const SEC = "===";   // section marker:  === STEM ===

export function buildWhole(q) {
  const stem = q.stem || "";
  const choices = (q.choices || []).map(c => `(${c.label}) ${c.text || ""}`).join("\n");
  const answer = q.answer || "";
  const solution = q.solution || "";
  return [
    `${SEC} STEM ${SEC}`,
    stem,
    "",
    `${SEC} CHOICES ${SEC}`,
    choices,
    "",
    `${SEC} ANSWER ${SEC}`,
    answer,
    "",
    `${SEC} SOLUTION ${SEC}`,
    solution,
  ].join("\n");
}

export function parseWhole(text) {
  const lines = text.split("\n");
  const sec = { stem: "", choices: "", answer: "", solution: "" };
  let cur = null;
  const choices = [];
  for (const raw of lines) {
    const h = raw.match(/^===\s*([A-Za-z]+)\s*===$/);
    if (h) { cur = h[1].toLowerCase(); continue; }
    if (cur === "choices") {
      const cm = raw.match(/^\s*\(([^)]+)\)\s?(.*)$/);
      if (cm) { choices.push({ label: cm[1], text: cm[2] }); continue; }
      // a non-empty line after a (X) line is a continuation of that choice; blank
      // separator lines between sections must not be glued onto the last choice
      if (choices.length && raw.trim() !== "") {
        choices[choices.length - 1].text += "\n" + raw;
        continue;
      }
    }
    if (cur && sec[cur] !== undefined) {
      sec[cur] += (sec[cur] ? "\n" : "") + raw;
    }
  }
  return {
    stem: sec.stem.trim(),
    choices,
    answer: sec.answer.trim(),
    solution: sec.solution.trim(),
  };
}

function fieldOf(fieldKey) {
  // "choice:3" -> ("choices", 3); "stem" -> ("stem", -1)
  if (fieldKey.startsWith("choice:")) {
    return ["choices", parseInt(fieldKey.split(":")[1], 10)];
  }
  return [fieldKey, -1];
}

async function validateWhole(qid, parsed) {
  const fields = [
    ["stem", parsed.stem],
    ["choices", parsed.choices],
    ["answer", parsed.answer],
    ["solution", parsed.solution],
  ];
  for (const [field, value] of fields) {
    try {
      const res = await api.validate(qid, field, value);
      if (!res.ok) return { ok: false, field, log: res.log };
    } catch (err) {
      return { ok: false, field, log: String(err.message || err) };
    }
  }
  return { ok: true, field: null, log: "" };
}

export function openWholeEditor(q, onSaved) {
  closeAll();
  const id = q.id;
  const initial = buildWhole(q);

  const wrap = document.createElement("div");
  wrap.className = "qedit-backdrop";
  wrap.innerHTML = `
    <div class="qedit-modal" role="dialog" aria-modal="true">
      <div class="qedit-head">
        <strong>Edit question LaTeX</strong>
        <span class="muted">${escAttr(id)}</span>
        <button class="qedit-x" title="Close">&times;</button>
      </div>
      <div class="qedit-hint">
        Edit the whole question as LaTeX. Sections:
        <code>=== STEM ===</code>, <code>=== CHOICES ===</code>,
        <code>=== ANSWER ===</code>, <code>=== SOLUTION ===</code>.
        Choices are one line each: <code>(A) …</code>.
      </div>
      <textarea class="qedit-area" spellcheck="false"></textarea>
      <div class="qedit-status"></div>
      <div class="qedit-foot">
        <button class="btn" data-act="cancel">Cancel</button>
        <button class="btn btn-primary" data-act="save">Save &amp; exit</button>
      </div>
    </div>`;
  root().appendChild(wrap);

  const area = wrap.querySelector(".qedit-area");
  const status = wrap.querySelector(".qedit-status");
  area.value = initial;

  let dirty = false;
  area.addEventListener("input", () => { dirty = area.value !== initial; });

  function close() {
    wrap.remove();
    document.removeEventListener("keydown", onKey, true);
  }

  async function doSave() {
    const parsed = parseWhole(area.value);
    status.className = "qedit-status";
    status.textContent = "Validating…";
    const v = await validateWhole(id, parsed);
    if (!v.ok) {
      status.className = "qedit-status err";
      status.textContent = `Cannot compile (${v.field}): ` +
        (v.log ? v.log.split("\n").filter(Boolean).slice(-6).join(" ") : "unknown error");
      return false;
    }
    try {
      await api.patch(id, {
        stem: parsed.stem, choices: parsed.choices,
        answer: parsed.answer, solution: parsed.solution,
      });
    } catch (err) {
      status.className = "qedit-status err";
      status.textContent = "Save failed: " + (err.message || err);
      return false;
    }
    if (onSaved) onSaved(parsed);
    return true;
  }

  async function attemptClose() {
    if (!dirty) { close(); return; }
    const choice = await confirmDiscard(wrap);
    if (choice === "cancel") return;
    if (choice === "discard") { close(); return; }
    const ok = await doSave();
    if (ok) close();
  }

  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); attemptClose(); }
  }
  document.addEventListener("keydown", onKey, true);

  wrap.querySelector('[data-act="save"]').onclick = async () => {
    const ok = await doSave();
    if (ok) close();
  };
  wrap.querySelector('[data-act="cancel"]').onclick = attemptClose;
  wrap.querySelector(".qedit-x").onclick = attemptClose;

  setTimeout(() => area.focus(), 30);
}

/* ----------------------------------------------------------------------- *
 * Single-formula / quantity popover
 * ----------------------------------------------------------------------- */

export function openMathPopup({ q, fieldKey, idx, anchorEl, commit }) {
  closeAll();
  const id = q.id;
  const [field, choiceIdx] = fieldOf(fieldKey);

  // current source for the field
  let src;
  if (field === "choices") src = (q.choices[choiceIdx] || {}).text || "";
  else src = q[field] || "";

  const initialBody = (extractMathRuns(src)[idx]?.body) ?? "";
  const display = anchorEl && anchorEl.dataset.display === "1";

  const pop = document.createElement("div");
  pop.className = "math-popup";
  pop.innerHTML = `
    <div class="mp-head">
      <span>Edit formula</span>
      <button class="mp-x" title="Close">&times;</button>
    </div>
    <textarea class="mp-area" spellcheck="false"></textarea>
    <div class="mp-preview"></div>
    <div class="mp-status"></div>`;
  root().appendChild(pop);

  const area = pop.querySelector(".mp-area");
  const preview = pop.querySelector(".mp-preview");
  const status = pop.querySelector(".mp-status");
  area.value = initialBody;

  positionPopup(pop, anchorEl);

  function render() {
    const tex = area.value;
    try {
      if (window.katex) {
        preview.innerHTML = window.katex.renderToString(tex, {
          displayMode: !!display, throwOnError: false, strict: "ignore",
        });
        preview.classList.remove("bad");
      }
      status.textContent = "";
      status.className = "mp-status";
    } catch (err) {
      preview.innerHTML = "";
      status.textContent = String(err.message || err);
      status.className = "mp-status err";
    }
  }
  area.addEventListener("input", render);
  render();

  function close() {
    pop.remove();
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("mousedown", onDown, true);
  }

  let settled = false;
  async function apply() {
    if (settled) return;
    settled = true;
    const newBody = area.value;
    if (newBody === initialBody) { close(); return; }

    // 1) quick client-side parse gate (instant)
    if (window.katex) {
      try {
        window.katex.renderToString(newBody, { displayMode: !!display, throwOnError: true });
      } catch (err) {
        toast("Invalid LaTeX — reverted to original");
        close();
        return;
      }
    }

    // 2) build the candidate field value with the run replaced
    let value;
    if (field === "choices") {
      value = q.choices.map((c, i) =>
        i === choiceIdx ? { ...c, text: replaceMathRun(c.text, idx, newBody) } : c);
    } else {
      value = replaceMathRun(src, idx, newBody);
    }

    // 3) compile-check on the server; revert if it fails
    let res;
    try {
      res = await api.validate(id, field, value);
    } catch (err) {
      toast("Validation error — reverted");
      close();
      return;
    }
    if (!res.ok) {
      toast("Cannot compile — reverted to original");
      close();
      return;
    }

    // 4) commit (PATCH + re-render) handled by the caller
    try {
      if (commit) await commit(field, value);
    } catch (err) {
      toast("Save failed — reverted");
      close();
      return;
    }
    close();
  }

  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); apply(); }
  }
  function onDown(e) {
    if (pop.contains(e.target)) return;
    if (anchorEl && anchorEl.contains(e.target)) return;
    apply();
  }
  document.addEventListener("keydown", onKey, true);
  document.addEventListener("mousedown", onDown, true);

  pop.querySelector(".mp-x").onclick = apply;
  // keep focus sensible
  setTimeout(() => area.focus(), 20);
}

/* ----------------------------------------------------------------------- *
 * helpers
 * ----------------------------------------------------------------------- */

function positionPopup(pop, anchorEl) {
  const r = anchorEl ? anchorEl.getBoundingClientRect() : null;
  pop.style.visibility = "hidden";
  pop.style.display = "block";
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  let top, left;
  if (r) {
    left = Math.min(r.left, window.innerWidth - pw - 8);
    left = Math.max(8, left);
    top = r.bottom + 8;
    if (top + ph > window.innerHeight - 8) {
      top = Math.max(8, r.top - ph - 8);
    }
  } else {
    left = Math.max(8, (window.innerWidth - pw) / 2);
    top = Math.max(8, (window.innerHeight - ph) / 2);
  }
  pop.style.left = left + "px";
  pop.style.top = top + "px";
  pop.style.visibility = "visible";
}

function confirmDiscard(within) {
  return new Promise((resolve) => {
    const ov = document.createElement("div");
    ov.className = "qedit-backdrop confirm";
    ov.innerHTML = `
      <div class="qedit-confirm" role="alertdialog">
        <p>You have unsaved changes. What would you like to do?</p>
        <div class="qedit-foot">
          <button class="btn" data-act="cancel">Keep editing</button>
          <button class="btn" data-act="discard">Discard</button>
          <button class="btn btn-primary" data-act="save">Save &amp; exit</button>
        </div>
      </div>`;
    root().appendChild(ov);
    function done(choice) {
      ov.remove();
      resolve(choice);
    }
    ov.querySelector('[data-act="cancel"]').onclick = () => done("cancel");
    ov.querySelector('[data-act="discard"]').onclick = () => done("discard");
    ov.querySelector('[data-act="save"]').onclick = () => done("save");
    ov.addEventListener("mousedown", (e) => { if (e.target === ov) done("cancel"); });
  });
}

function closeAll() {
  const r = root();
  if (r) [...r.children].forEach(c => c.remove());
}
