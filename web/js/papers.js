import { api } from "./api.js";
import * as compose from "./compose.js";
import { getUser, toast } from "./session.js";

// My Papers: my own saved papers, plus papers colleagues shared with me.
//
// The split mirrors the backend.  A draft is private and editable; a shared paper
// is an immutable revision someone published, so the only thing I can do with it
// is build it or save my own copy.

let els = {};
let state = { drafts: [], shared: [], folders: [], people: [], notifications: [] };
let activeDraftId = null;

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function questionCount(ids) {
  return (ids || []).length;
}

export function init() {
  els = {
    list: document.getElementById("p-list"),
    title: document.getElementById("p-title"),
    status: document.getElementById("p-status"),
    save: document.getElementById("p-save"),
    rename: document.getElementById("p-name"),
    shared: document.getElementById("p-shared"),
    notifications: document.getElementById("p-notifications"),
    bell: document.getElementById("p-bell"),
  };

  if (els.save) els.save.onclick = saveCurrent;
  if (els.bell) els.bell.onclick = openNotifications;
  refresh();
}

function setStatus(message, isError = false) {
  if (!els.status) return;
  els.status.textContent = message || "";
  els.status.className = "status" + (isError ? " err" : " ok");
}

export async function refresh() {
  try {
    const [drafts, sharing] = await Promise.all([api.drafts(), api.sharing()]);
    state.drafts = drafts.drafts || [];
    state.shared = sharing.publications || [];
    state.folders = sharing.folders || [];
    state.people = sharing.people || [];
    state.notifications = sharing.notifications || [];
    renderBell(sharing.unread_notification_count || 0);
    render();
  } catch (err) {
    setStatus(String(err.message || err), true);
  }
}

function renderBell(unread) {
  if (!els.bell) return;
  els.bell.textContent = unread ? `Notifications (${unread})` : "Notifications";
  els.bell.classList.toggle("badge-notify", unread > 0);
}

// --------------------------------------------------------------------------------------
// rendering
// --------------------------------------------------------------------------------------

function render() {
  if (!els.list) return;
  const mine = state.drafts.filter(d => !d.copied_from_revision_id || true);
  els.list.innerHTML = `
    <div class="paper-group">
      <h3 class="paper-group-head">My papers <span class="pill">${mine.length}</span></h3>
      ${mine.length ? mine.map(draftCard).join("") : emptyRow("No saved papers yet.")}
    </div>
    <div class="paper-group">
      <h3 class="paper-group-head">Shared with me <span class="pill">${state.shared.length}</span></h3>
      ${state.shared.length ? state.shared.map(sharedCard).join("") : emptyRow("Nothing has been shared yet.")}
    </div>`;

  els.list.querySelectorAll("[data-open-draft]").forEach(btn => {
    btn.onclick = () => openDraft(Number(btn.dataset.openDraft));
  });
  els.list.querySelectorAll("[data-del-draft]").forEach(btn => {
    btn.onclick = async () => {
      try {
        await api.deleteDraft(Number(btn.dataset.delDraft));
        if (activeDraftId === Number(btn.dataset.delDraft)) activeDraftId = null;
        await refresh();
        toast("Paper deleted.");
      } catch (err) { setStatus(String(err.message || err), true); }
    };
  });
  els.list.querySelectorAll("[data-share-draft]").forEach(btn => {
    btn.onclick = () => openShareDialog(Number(btn.dataset.shareDraft));
  });
  els.list.querySelectorAll("[data-copy-shared]").forEach(btn => {
    btn.onclick = async () => {
      const id = Number(btn.dataset.copyShared);
      const revision = Number(btn.dataset.revision || 0) || null;
      try {
        const res = await api.copyShared(id, null, revision);
        await refresh();
        await openDraft(res.draft.id);
        toast("Saved as your own paper.");
      } catch (err) { setStatus(String(err.message || err), true); }
    };
  });
}

function emptyRow(text) {
  return `<p class="muted small paper-empty">${escapeHtml(text)}</p>`;
}

function draftCard(draft) {
  const active = draft.id === activeDraftId;
  const update = draft.source_update;
  return `
    <div class="paper-card${active ? " active" : ""}">
      <div class="paper-card-top">
        <strong>${escapeHtml(draft.name)}</strong>
        <span class="muted small">${questionCount(draft.question_ids)} questions ·
          updated ${escapeHtml((draft.updated_at || "").slice(0, 16))}</span>
      </div>
      ${update ? `<p class="paper-update">New version available:
        ${escapeHtml(update.title)} (rev ${update.latest_revision_number})</p>` : ""}
      <div class="btn-row">
        <button class="btn" data-open-draft="${draft.id}">Open</button>
        <button class="btn btn-ghost" data-share-draft="${draft.id}">Share</button>
        <button class="btn btn-ghost danger" data-del-draft="${draft.id}">Delete</button>
      </div>
    </div>`;
}

function sharedCard(pub) {
  return `
    <div class="paper-card">
      <div class="paper-card-top">
        <strong>${escapeHtml(pub.title)}</strong>
        <span class="muted small">from ${escapeHtml(pub.owner_display_name || "a colleague")}
          · ${questionCount(pub.question_ids)} questions · rev ${pub.revision_number}</span>
      </div>
      ${pub.is_owner ? `<p class="paper-update">You shared this
        ${pub.has_unpublished_changes ? "· you have unpublished changes" : ""}</p>` : ""}
      <div class="btn-row">
        <button class="btn" data-copy-shared="${pub.id}"
          data-revision="${pub.revision_id || ""}">Save a copy</button>
        ${pub.is_owner ? `<button class="btn btn-ghost danger"
          data-withdraw="${pub.id}">Withdraw</button>` : ""}
      </div>
    </div>`;
}

// --------------------------------------------------------------------------------------
// actions
// --------------------------------------------------------------------------------------

async function saveCurrent() {
  if (!compose.hasSelection()) { setStatus("Nothing selected in Compose.", true); return; }
  const name = (els.rename && els.rename.value.trim()) || "Untitled paper";
  try {
    const body = {
      name,
      question_ids: compose.selectionIds(),
      settings: compose.exportOptions(),
      metadata: { title: name },
    };
    if (activeDraftId) {
      const existing = state.drafts.find(d => d.id === activeDraftId);
      if (existing) {
        body.id = existing.id;
        body.version = existing.version;
      }
    }
    const res = await api.saveDraft(body);
    activeDraftId = res.draft.id;
    if (els.rename) els.rename.value = res.draft.name;
    await refresh();
    setStatus(`Saved "${res.draft.name}".`);
  } catch (err) {
    setStatus(String(err.message || err), true);
  }
}

async function openDraft(id) {
  const draft = state.drafts.find(d => d.id === id);
  if (!draft) return;
  activeDraftId = id;
  try {
    const res = await api.questions({ limit: 2000 });
    const byId = new Map((res.questions || []).map(q => [q.id, q]));
    const ordered = draft.question_ids.map(qid => byId.get(qid)).filter(Boolean);
    compose.setSelection(ordered);
    compose.applyOptions(draft.settings || {});
    if (els.rename) els.rename.value = draft.name;
    const missing = draft.question_ids.length - ordered.length;
    toast(`Opened "${draft.name}"${missing ? ` (${missing} missing)` : ""}.`);
    render();
    // Send the teacher straight to Compose, which now shows the loaded paper.
    document.querySelector('.tab[data-view="compose"]')?.click();
  } catch (err) {
    setStatus(String(err.message || err), true);
  }
}

// --------------------------------------------------------------------------------------
// share dialog
// --------------------------------------------------------------------------------------

function openShareDialog(draftId) {
  const draft = state.drafts.find(d => d.id === draftId);
  if (!draft) return;
  const root = document.getElementById("login-root");
  const me = getUser();
  const existing = state.shared.find(p => p.source_draft_id === draftId && p.is_owner);

  const people = state.people.filter(p => !me || p.id !== me.id);
  root.innerHTML = `
    <div class="login-backdrop">
      <div class="login-card wide">
        <h2>Share "${escapeHtml(draft.name)}"</h2>
        <p class="muted small">
          Colleagues can read, build and copy this paper. They never edit your copy,
          and each publish is a fixed snapshot.
        </p>
        <label class="lbl" for="sh-title">Title</label>
        <input id="sh-title" class="input" value="${escapeHtml(existing?.title || draft.name)}" />
        <label class="lbl" for="sh-message">Message (optional)</label>
        <input id="sh-message" class="input" value="${escapeHtml(existing?.message || "")}" />
        <label class="lbl">Sharing groups</label>
        <div class="share-options">
          ${state.folders.length ? state.folders.map(f => `
            <label class="chk"><input type="checkbox" class="sh-folder" value="${f.id}"
              ${(existing?.folders || []).includes(f.id) ? "checked" : ""} />
              ${escapeHtml(f.name)}</label>`).join("")
            : `<span class="muted small">No sharing groups yet.</span>`}
        </div>
        <label class="lbl">Colleagues</label>
        <div class="share-options">
          ${people.map(p => `
            <label class="chk"><input type="checkbox" class="sh-person" value="${p.id}"
              ${(existing?.recipients || []).includes(p.id) ? "checked" : ""} />
              ${escapeHtml(p.display_name || p.username)}</label>`).join("")}
        </div>
        <p id="sh-status" class="status"></p>
        <div class="btn-row">
          <button class="btn btn-primary" id="sh-publish">Publish</button>
          <button class="btn btn-ghost" id="sh-close">Close</button>
        </div>
      </div>
    </div>`;
  root.hidden = false;

  document.getElementById("sh-close").onclick = () => { root.hidden = true; root.innerHTML = ""; };
  document.getElementById("sh-publish").onclick = async () => {
    const status = document.getElementById("sh-status");
    const folderIds = [...root.querySelectorAll(".sh-folder:checked")].map(i => Number(i.value));
    const personIds = [...root.querySelectorAll(".sh-person:checked")].map(i => Number(i.value));
    try {
      await api.publish({
        draft_id: draftId,
        title: document.getElementById("sh-title").value.trim() || draft.name,
        message: document.getElementById("sh-message").value.trim(),
        folder_ids: folderIds,
        recipient_ids: personIds,
        version: existing ? existing.version : null,
      });
      status.textContent = "Shared.";
      status.className = "status ok";
      await refresh();
      setTimeout(() => { root.hidden = true; root.innerHTML = ""; }, 900);
    } catch (err) {
      status.textContent = String(err.message || err).replace(/^\d+\s*/, "");
      status.className = "status err";
    }
  };
}

function openNotifications() {
  const root = document.getElementById("login-root");
  const items = state.notifications.slice(0, 40);
  root.innerHTML = `
    <div class="login-backdrop">
      <div class="login-card">
        <h2>Notifications</h2>
        ${items.length ? `<ul class="notif-list">${items.map(n => `
          <li class="${n.read_at ? "" : "unread"}">
            <span class="tag">${escapeHtml(n.event_type)}</span>
            <span>${escapeHtml(n.message)}</span>
            <span class="muted small">${escapeHtml((n.created_at || "").slice(0, 16))}</span>
          </li>`).join("")}</ul>`
        : `<p class="muted small">Nothing yet.</p>`}
        <div class="btn-row">
          <button class="btn" id="nf-read">Mark all read</button>
          <button class="btn btn-ghost" id="nf-close">Close</button>
        </div>
      </div>
    </div>`;
  root.hidden = false;
  document.getElementById("nf-close").onclick = () => { root.hidden = true; root.innerHTML = ""; };
  document.getElementById("nf-read").onclick = async () => {
    await api.readNotifications([]);
    await refresh();
    root.hidden = true; root.innerHTML = "";
  };
}
