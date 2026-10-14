import { api, setExpectedUserId } from "./api.js";

// The signed-in account, or null while the sign-in screen is up.
let currentUser = null;
let onChanged = () => {};

export function getUser() {
  return currentUser;
}

export function isAdmin() {
  return !!currentUser && currentUser.role === "admin";
}

function avatarInitials(user) {
  const source = (user.display_name || user.username || "?").trim();
  return source.slice(0, 2).toUpperCase();
}

function paintUserChip() {
  const chip = document.getElementById("user-chip");
  if (!chip) return;
  if (!currentUser) {
    chip.innerHTML = "";
    chip.hidden = true;
    return;
  }
  chip.hidden = false;
  chip.innerHTML = `
    <span class="avatar">${avatarInitials(currentUser)}</span>
    <span class="user-chip-text">
      <strong>${escapeHtml(currentUser.display_name || currentUser.username)}</strong>
      <span class="muted small">${escapeHtml(currentUser.role)}</span>
    </span>`;
}

function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.className = "toast show" + (isError ? " err" : "");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => { toast.className = "toast"; }, 4000);
}

export function toast(message, isError = false) {
  showToast(message, isError);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

// --------------------------------------------------------------------------------------
// sign-in screen
// --------------------------------------------------------------------------------------

function renderLoginScreen(message) {
  const root = document.getElementById("login-root");
  if (!root) return;
  root.innerHTML = `
    <div class="login-backdrop">
      <form class="login-card" id="login-form" autocomplete="on">
        <div class="login-brand">
          <span class="brand-mark">AP&nbsp;C</span>
          <div>
            <strong>AP Physics C: Mechanics</strong>
            <span class="muted small">Question Bank</span>
          </div>
        </div>
        <h2>Sign in</h2>
        ${message ? `<p class="login-error">${escapeHtml(message)}</p>` : ""}
        <label class="lbl" for="login-username">Username</label>
        <input id="login-username" class="input" autocomplete="username" required />
        <label class="lbl" for="login-password">Password</label>
        <input id="login-password" class="input" type="password"
               autocomplete="current-password" required />
        <button class="btn btn-primary login-submit" type="submit">Sign in</button>
        <p class="muted small login-hint">
          First run: sign in as <code>admin</code> with the password
          <code>admin</code>, then change it under Account.
        </p>
      </form>
    </div>`;
  root.hidden = false;

  const form = document.getElementById("login-form");
  form.onsubmit = async (event) => {
    event.preventDefault();
    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value;
    try {
      await api.login(username, password);
      await resolveSession();
      root.hidden = true;
      root.innerHTML = "";
      onChanged(currentUser);
    } catch (err) {
      renderLoginScreen(String(err.message || err).replace(/^\d+\s*/, ""));
    }
  };
  document.getElementById("login-username").focus();
}

function hideLoginScreen() {
  const root = document.getElementById("login-root");
  if (root) { root.hidden = true; root.innerHTML = ""; }
}

async function resolveSession() {
  const data = await api.session();
  currentUser = data.user || null;
  setExpectedUserId(currentUser ? currentUser.id : null);
  paintUserChip();
  return currentUser;
}

// --------------------------------------------------------------------------------------
// account menu
// --------------------------------------------------------------------------------------

function openAccountDialog() {
  const root = document.getElementById("login-root");
  if (!root || !currentUser) return;
  root.innerHTML = `
    <div class="login-backdrop">
      <div class="login-card">
        <h2>Account</h2>
        <p class="muted small">
          Signed in as <strong>${escapeHtml(currentUser.username)}</strong>
          (${escapeHtml(currentUser.role)}).
        </p>
        <label class="lbl" for="pw-current">Current password</label>
        <input id="pw-current" class="input" type="password" autocomplete="current-password" />
        <label class="lbl" for="pw-new">New password</label>
        <input id="pw-new" class="input" type="password" autocomplete="new-password" />
        <p class="muted small">At least 8 characters. Other devices stay signed out.</p>
        <div class="btn-row">
          <button class="btn btn-primary" id="pw-save">Change password</button>
          <button class="btn btn-ghost" id="pw-close">Close</button>
        </div>
        <p id="pw-status" class="status"></p>
      </div>
    </div>`;
  root.hidden = false;

  document.getElementById("pw-close").onclick = () => hideLoginScreen();
  document.getElementById("pw-save").onclick = async () => {
    const status = document.getElementById("pw-status");
    try {
      await api.changePassword(
        document.getElementById("pw-current").value,
        document.getElementById("pw-new").value);
      status.textContent = "Password changed.";
      status.className = "status ok";
    } catch (err) {
      status.textContent = String(err.message || err).replace(/^\d+\s*/, "");
      status.className = "status err";
    }
  };
}

// --------------------------------------------------------------------------------------
// boot
// --------------------------------------------------------------------------------------

export async function initSession(options = {}) {
  onChanged = options.onChanged || (() => {});
  try {
    const data = await api.session();
    if (data.user) {
      currentUser = data.user;
      setExpectedUserId(currentUser.id);
      paintUserChip();
      hideLoginScreen();
      return currentUser;
    }
    if (!data.login_required) {
      // Single-user install: the backend attributes everything to the admin.
      currentUser = null;
      hideLoginScreen();
      return currentUser;
    }
    renderLoginScreen("");
    return null;
  } catch (err) {
    renderLoginScreen(String(err.message || err));
    return null;
  }
}

export function installAccountMenu() {
  const chip = document.getElementById("user-chip");
  if (chip) chip.onclick = openAccountDialog;
  const signOut = document.getElementById("sign-out");
  if (signOut) {
    signOut.onclick = async () => {
      try {
        await api.logout();
      } finally {
        currentUser = null;
        setExpectedUserId(null);
        paintUserChip();
        location.reload();
      }
    };
  }
}
