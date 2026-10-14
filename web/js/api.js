const JSON_HEADERS = {"Content-Type": "application/json"};

// All tabs in one browser profile share the session cookie.  Sending the account
// we *think* we are lets the backend reject a stale tab before it writes, so one
// teacher's work can never land on another teacher's account.
let expectedUserId = null;

export function setExpectedUserId(id) {
  expectedUserId = id == null ? null : Number(id);
}

function withGuard(options = {}) {
  if (!expectedUserId) return options;
  const headers = new Headers(options.headers || {});
  headers.set("X-QB-Expected-User-Id", String(expectedUserId));
  return { ...options, headers };
}

async function request(url, options = {}) {
  const res = await fetch(url, withGuard(options));
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || data.error || JSON.stringify(data);
    } catch (_) { /* keep statusText */ }
    throw new Error(`${res.status} ${detail}`);
  }
  const type = res.headers.get("content-type") || "";
  return type.includes("application/json") ? res.json() : res;
}

export const api = {
  health:  () => request("/api/health"),
  taxonomy: () => request("/api/taxonomy"),
  stats:   () => request("/api/stats"),

  questions(params = {}) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== "" && v !== false && v != null) qs.set(k, v);
    }
    return request("/api/questions?" + qs.toString());
  },

  question: (id) => request("/api/questions/" + encodeURIComponent(id)),
  questionTex: (id) => request("/api/questions/" + encodeURIComponent(id) + "/tex").then(r => r.text()),
  patch: (id, body) => request("/api/questions/" + encodeURIComponent(id), {
    method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body),
  }),
  validate: (id, field, value) => request("/api/questions/" + encodeURIComponent(id) + "/validate", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ field, value }),
  }),
  remove: (id) => request("/api/questions/" + encodeURIComponent(id), { method: "DELETE" }),

  exportTex: (body) => request("/api/export/latex", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body),
  }),
  exportPdf: async (body, filename) => {
    const res = await fetch("/api/export/pdf", {
      method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.log || res.statusText);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  },

  ingestUpload: async (file, docId, dpi) => {
    const form = new FormData();
    form.append("file", file);
    if (docId) form.append("doc_id", docId);
    form.append("dpi", String(dpi));
    return request("/api/ingest", { method: "POST", body: form });
  },
  ingestJobs: () => request("/api/ingest"),
  ingestJob:  (job) => request("/api/ingest/" + job),
  ingestPolish: (job, limit) => request(`/api/ingest/${job}/polish` + (limit ? `?limit=${limit}` : ""),
                                        { method: "POST" }),
  ingestCommit: (job) => request(`/api/ingest/${job}/commit`, { method: "POST" }),
  ingestDelete: (job) => request("/api/ingest/" + job, { method: "DELETE" }),

  // ---- accounts ----
  session: () => request("/api/session"),
  login: (username, password) => request("/api/session", {
    method: "POST", headers: JSON_HEADERS,
    body: JSON.stringify({ username, password }),
  }),
  logout: () => request("/api/logout", { method: "POST", headers: JSON_HEADERS, body: "{}" }),
  changePassword: (current_password, new_password) => request("/api/profile/password", {
    method: "POST", headers: JSON_HEADERS,
    body: JSON.stringify({ current_password, new_password }),
  }),
  users: () => request("/api/users"),
  saveUser: (body) => request("/api/users", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body),
  }),
  activity: (params = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== "" && v != null) qs.set(k, v);
    }
    return request("/api/activity?" + qs.toString());
  },

  // ---- saved papers ----
  drafts: () => request("/api/paper-drafts"),
  saveDraft: (body) => request("/api/paper-drafts", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body),
  }),
  deleteDraft: (id) => request("/api/paper-drafts/delete", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ id }),
  }),

  // ---- sharing ----
  sharing: () => request("/api/paper-sharing"),
  saveFolder: (body) => request("/api/paper-folders", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body),
  }),
  archiveFolder: (id) => request("/api/paper-folders/archive", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ id }),
  }),
  publish: (body) => request("/api/paper-publications", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body),
  }),
  withdraw: (publication_id) => request("/api/paper-publications/withdraw", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ publication_id }),
  }),
  copyShared: (publication_id, name, revision_id) =>
    request("/api/paper-publications/copy", {
      method: "POST", headers: JSON_HEADERS,
      body: JSON.stringify({ publication_id, name, revision_id }),
    }),
  subscribe: (publication_id, follow) => request("/api/paper-subscriptions", {
    method: "POST", headers: JSON_HEADERS,
    body: JSON.stringify({ publication_id, follow }),
  }),
  readNotifications: (ids = []) => request("/api/paper-notifications/read", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ notification_ids: ids }),
  }),
};
