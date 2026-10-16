import { api } from "./api.js";

// Tagging.
//
// A question can carry any number of free-text tags. The vocabulary is whatever
// teachers have already typed, so the editor offers those for reuse instead of
// letting "projectile", "Projectiles" and "projectile motion" all appear.

let cache = null;

export async function vocabulary() {
  if (!cache) {
    const payload = await api.tags();
    cache = (payload.tags || []).map(t => t.name);
  }
  return cache;
}

export function invalidate() {
  cache = null;
}

export { invalidate as invalidateTags };

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

/**
 * Render a tag editor into `container`.
 *
 * `onChange(nextTags)` is called with the whole new list, so the caller only has
 * to persist it -- adding and removing are the same operation.
 */
export async function renderTagEditor(container, { tags = [], onChange }) {
  let current = [...tags];
  const known = await vocabulary();

  function commit(next) {
    current = next;
    paint();
    if (onChange) onChange(current);
  }

  function add(name) {
    const clean = String(name || "").trim();
    if (!clean) return;
    // Case-insensitive de-duplication, matching the server.
    if (current.some(t => t.toLowerCase() === clean.toLowerCase())) return;
    commit([...current, clean]);
  }

  function remove(name) {
    commit(current.filter(t => t !== name));
  }

  function paint() {
    const input = container.querySelector(".tag-input");
    const typed = input ? input.value.trim().toLowerCase() : "";
    const suggestions = known
      .filter(name => !current.some(t => t.toLowerCase() === name.toLowerCase()))
      .filter(name => !typed || name.toLowerCase().includes(typed))
      .slice(0, 12);

    container.innerHTML = `
      <div class="tag-chips">
        ${current.map(name => `
          <span class="tag-chip">
            <span class="tag-chip-name">${escapeHtml(name)}</span>
            <button class="tag-chip-x" data-remove="${escapeHtml(name)}"
                    title="Remove tag">&times;</button>
          </span>`).join("")}
        ${current.length ? "" : `<span class="muted small">No tags yet.</span>`}
      </div>
      <input class="input tag-input" placeholder="Add a tag…"
             list="tag-options" autocomplete="off" />
      <datalist id="tag-options">
        ${known.map(name => `<option value="${escapeHtml(name)}"></option>`).join("")}
      </datalist>
      ${suggestions.length ? `
        <div class="tag-suggestions">
          ${suggestions.map(name => `
            <button class="tag-suggestion" data-add="${escapeHtml(name)}">
              ${escapeHtml(name)}
            </button>`).join("")}
        </div>` : ""}`;

    const input2 = container.querySelector(".tag-input");
    input2.value = input ? input.value : "";
    input2.oninput = () => paint();
    input2.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === ",") {
        event.preventDefault();
        add(input2.value);
        input2.value = "";
      } else if (event.key === "Backspace" && !input2.value && current.length) {
        remove(current[current.length - 1]);
      }
    };
    container.querySelectorAll("[data-remove]").forEach(button => {
      button.onclick = () => remove(button.dataset.remove);
    });
    container.querySelectorAll("[data-add]").forEach(button => {
      button.onclick = () => {
        add(button.dataset.add);
        input2.value = "";
      };
    });
  }

  paint();
  return {
    value: () => current,
  };
}
