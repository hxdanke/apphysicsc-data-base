import { api, setCourse, getCourse } from "./api.js";

// The course switcher in the top-left corner, plus a cache of each course's
// taxonomy so the topic picker does not refetch it on every open.

let courses = [];
let onSwitch = () => {};
const taxonomyCache = new Map();

export function list() {
  return courses;
}

export function current() {
  return courses.find(c => c.id === getCourse()) || courses[0] || null;
}

const STORAGE_KEY = "qb.course";

export async function init(options = {}) {
  onSwitch = options.onSwitch || (() => {});
  const payload = await api.courses();
  courses = payload.courses || [];

  const stored = localStorage.getItem(STORAGE_KEY);
  const wanted = courses.find(c => c.id === stored) ? stored : payload.default;
  setCourse(wanted);
  renderSwitcher();
  return current();
}

export function renderSwitcher() {
  const host = document.getElementById("course-switch");
  if (!host) return;
  const active = current();
  host.innerHTML = `
    <button class="course-button" id="course-button" title="Switch course">
      <span class="course-badge">${escapeHtml(active ? active.short : "—")}</span>
      <span class="course-name">${escapeHtml(active ? active.title : "No course")}</span>
      <span class="course-caret">▾</span>
    </button>
    <div class="course-menu" id="course-menu" hidden>
      ${courses.map(c => `
        <button class="course-option${c.id === getCourse() ? " active" : ""}"
                data-course="${c.id}">
          <span class="course-option-main">${escapeHtml(c.title)}</span>
          <span class="course-option-count">${c.questions}</span>
        </button>`).join("")}
    </div>`;

  const menu = document.getElementById("course-menu");
  const button = document.getElementById("course-button");
  button.onclick = (event) => {
    // Stop the click reaching the document handler, which would close the menu
    // again in the same event and make the toggle look dead.
    event.stopPropagation();
    menu.hidden = !menu.hidden;
    button.setAttribute("aria-expanded", String(!menu.hidden));
  };
  menu.querySelectorAll("[data-course]").forEach(option => {
    option.onclick = async () => {
      menu.hidden = true;
      button.setAttribute("aria-expanded", "false");
      await switchTo(option.dataset.course);
    };
  });
}

export async function switchTo(courseId) {
  if (!courseId || courseId === getCourse()) return;
  setCourse(courseId);
  taxonomyCache.clear();
  localStorage.setItem(STORAGE_KEY, courseId);
  renderSwitcher();
  await onSwitch(current());
}

/** Close the switcher when clicking anywhere else, or pressing Escape. */
export function installOutsideClick() {
  document.addEventListener("click", () => {
    const menu = document.getElementById("course-menu");
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    const button = document.getElementById("course-button");
    if (button) button.setAttribute("aria-expanded", "false");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const menu = document.getElementById("course-menu");
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    const button = document.getElementById("course-button");
    if (button) button.setAttribute("aria-expanded", "false");
  });
}

/** This course's unit/topic tree, cached. */
export async function taxonomy() {
  const id = getCourse();
  if (!taxonomyCache.has(id)) {
    taxonomyCache.set(id, await api.taxonomy());
  }
  return taxonomyCache.get(id);
}

export function invalidateTaxonomy() {
  taxonomyCache.delete(getCourse());
}

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

// --------------------------------------------------------------------------------------
// topic picker
// --------------------------------------------------------------------------------------

/**
 * Render a multi-select list of every knowledge block in the current course.
 *
 * The first pick is the primary topic (the one the question is filed under); the
 * rest are additional blocks the question also draws on.
 */
export function renderTopicPicker(container, taxonomy, options = {}) {
  const selected = new Set(options.selected || []);
  const primary = options.primary || "";
  let ordered = [primary, ...(options.selected || [])].filter(Boolean);
  ordered = [...new Set(ordered)];

  container.innerHTML = taxonomy.units.map(unit => `
    <div class="topic-group">
      <div class="topic-group-head">Unit ${unit.id} · ${escapeHtml(unit.title)}</div>
      ${unit.topics.map(topic => `
        <label class="topic-option">
          <input type="checkbox" class="topic-check" value="${topic.id}"
                 ${ordered.includes(topic.id) ? "checked" : ""} />
          <span class="topic-id">${topic.id}</span>
          <span class="topic-title">${escapeHtml(topic.title)}</span>
          <span class="topic-primary" data-primary-for="${topic.id}">
            ${topic.id === primary ? "primary" : ""}
          </span>
        </label>`).join("")}
    </div>`).join("");

  const read = () => {
    const picked = [...container.querySelectorAll(".topic-check:checked")]
      .map(input => input.value);
    return picked;
  };

  const sync = () => {
    const picked = read();
    // The primary is always the first ticked box, so the badge stays honest.
    if (ordered.length && !picked.includes(ordered[0])) {
      ordered = picked.slice();
    } else if (ordered.length && picked.length) {
      ordered = [ordered[0], ...picked.filter(id => id !== ordered[0])];
    } else {
      ordered = picked.slice();
    }
    container.querySelectorAll(".topic-primary").forEach(badge => {
      badge.textContent = badge.dataset.primaryFor === ordered[0] ? "primary" : "";
    });
  };

  container.querySelectorAll(".topic-check").forEach(input => {
    input.addEventListener("change", sync);
  });

  return {
    /** The primary topic id (first selected), or "". */
    primaryId: () => read()[0] || "",
    /** Every selected topic, primary first. */
    values: () => {
      const picked = read();
      return picked;
    },
    /** Everything after the primary. */
    additional: () => {
      const picked = read();
      return picked.slice(1);
    },
    selected: read,
  };
}

/**
 * Let a question already in the bank gain (or drop) knowledge blocks.
 *
 * The first ticked box is the primary topic, so this doubles as "move this
 * question to another unit" without a separate control.
 */
export async function openTopicEditor(question, onSaved) {
  const root = document.getElementById("login-root");
  const taxonomy = await taxonomyForCurrent();
  root.innerHTML = `
    <div class="login-backdrop">
      <div class="login-card wide">
        <h2>Knowledge blocks</h2>
        <p class="muted small">
          ${escapeHtml(question.id)} — the first block you tick is the primary
          topic; the rest are shown as additional.
        </p>
        <div class="topic-picker" id="te-picker"></div>
        <p id="te-status" class="status"></p>
        <div class="btn-row">
          <button class="btn btn-primary" id="te-save">Save</button>
          <button class="btn btn-ghost" id="te-close">Close</button>
        </div>
      </div>
    </div>`;
  root.hidden = false;

  const picker = renderTopicPicker(document.getElementById("te-picker"), taxonomy, {
    primary: question.topic || "",
    selected: [question.topic, ...(question.additional_topics || [])].filter(Boolean),
  });

  const close = () => { root.hidden = true; root.innerHTML = ""; };
  document.getElementById("te-close").onclick = close;
  document.getElementById("te-save").onclick = async () => {
    const status = document.getElementById("te-status");
    const topic = picker.primaryId();
    if (!topic) {
      status.textContent = "Choose at least one knowledge block.";
      status.className = "status err";
      return;
    }
    try {
      const { api } = await import("./api.js");
      const saved = await api.patch(question.id, {
        topic,
        additional_topics: picker.additional(),
      });
      close();
      onSaved(saved);
    } catch (err) {
      status.textContent = String(err.message || err).replace(/^\d+\s*/, "");
      status.className = "status err";
    }
  };
}

async function taxonomyForCurrent() {
  const { api } = await import("./api.js");
  const id = getCourse();
  if (!taxonomyCache.has(id)) taxonomyCache.set(id, await api.taxonomy());
  return taxonomyCache.get(id);
}
