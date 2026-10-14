import { api } from "./api.js";

// Admin-only view: who can sign in, and what they did recently.

let els = {};

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function setStatus(message, isError = false) {
  els.status.textContent = message || "";
  els.status.className = "status" + (isError ? " err" : " ok");
}

export function init() {
  els = {
    username: document.getElementById("u-username"),
    display: document.getElementById("u-display"),
    role: document.getElementById("u-role"),
    password: document.getElementById("u-password"),
    active: document.getElementById("u-active"),
    create: document.getElementById("u-create"),
    list: document.getElementById("u-list"),
    activity: document.getElementById("u-activity"),
    status: document.getElementById("u-status"),
  };
  if (!els.create) return;
  els.create.onclick = createAccount;
}

export async function refresh() {
  if (!els.list) return;
  try {
    const [users, activity] = await Promise.all([
      api.users(), api.activity({ limit: 60 }),
    ]);
    els.list.innerHTML = (users.users || []).map(u => `
      <div class="qcard">
        <div class="qcard-top">
          <span class="qcard-id">${escapeHtml(u.display_name || u.username)}</span>
          <span class="qcard-tags">
            <span class="tag">${escapeHtml(u.role)}</span>
            <span class="tag ${u.active ? "" : "tag-warn"}">${u.active ? "active" : "disabled"}</span>
          </span>
        </div>
        <div class="qcard-body muted small">
          ${escapeHtml(u.username)}${u.last_login_at ? ` · last login ${escapeHtml(u.last_login_at.slice(0, 16))}` : " · never signed in"}
        </div>
      </div>`).join("") || `<p class="muted small">No accounts yet.</p>`;

    els.activity.innerHTML = (activity.activity || []).map(a => `
      <div class="activity-row">
        <span class="tag">${escapeHtml(a.action)}</span>
        <span>${escapeHtml(a.summary || "")}</span>
        <span class="muted small">${escapeHtml(a.username || "")} · ${escapeHtml((a.created_at || "").slice(0, 16))}</span>
      </div>`).join("") || `<p class="muted small">No activity yet.</p>`;
  } catch (err) {
    setStatus(String(err.message || err), true);
  }
}

async function createAccount() {
  try {
    await api.saveUser({
      username: els.username.value.trim(),
      display_name: els.display.value.trim(),
      role: els.role.value,
      password: els.password.value,
      active: els.active.checked,
    });
    els.username.value = "";
    els.display.value = "";
    els.password.value = "";
    setStatus("Account created.");
    await refresh();
  } catch (err) {
    setStatus(String(err.message || err).replace(/^\d+\s*/, ""), true);
  }
}
