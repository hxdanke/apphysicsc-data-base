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

// The course the whole UI is currently pointed at.  Banks are separate, so
// every bank-scoped call carries it; nothing reaches across courses.
let currentCourse = "";

export function setCourse(id) {
  currentCourse = id || "";
}

export function getCourse() {
  return currentCourse;
}

/** Append the active course to a query string. */
function cq(params = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== "" && v !== false && v != null) qs.set(k, v);
  }
  if (currentCourse) qs.set("course", currentCourse);
  return qs.toString();
}

/** The same course, for request bodies. */
function cb(body = {}) {
  return currentCourse ? { ...body, course: currentCourse } : body;
}

export const api = {
  courses: () => request("/api/courses"),
  health:  () => request("/api/health?" + cq()),
  taxonomy: () => request("/api/taxonomy?" + cq()),
  stats:   () => request("/api/stats?" + cq()),

  questions(params = {}) {
    return request("/api/questions?" + cq(params));
  },

  question: (id) => request("/api/questions/" + encodeURIComponent(id) + "?" + cq()),
  questionTex: (id) => request("/api/questions/" + encodeURIComponent(id) + "/tex?" + cq())
    .then(r => r.text()),
  patch: (id, body) => request("/api/questions/" + encodeURIComponent(id) + "?" + cq(), {
    method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body),
  }),
  validate: (id, field, value) => request(
    "/api/questions/" + encodeURIComponent(id) + "/validate?" + cq(), {
      method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ field, value }),
    }),
  /** Whole-question compile check for the live preview. */
  preview: (body) => request("/api/questions/preview?" + cq(), {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body),
  }),
  /** Deleting moves the question to the recycle bin; it is not destroyed. */
  remove: (id) => request("/api/questions/" + encodeURIComponent(id) + "?" + cq(),
                          { method: "DELETE" }),

  // ---- recycle bin ----
  recycle: () => request("/api/recycle?" + cq()),
  recycleRestore: (id) => request("/api/recycle/restore?" + cq(), {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ id }),
  }),
  recyclePurge: (id) => request("/api/recycle/purge?" + cq(), {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ id }),
  }),
  recycleEmpty: () => request("/api/recycle/empty?" + cq(),
                              { method: "POST", headers: JSON_HEADERS, body: "{}" }),

  // ---- authoring ----
  author: (body) => request("/api/questions", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify(cb(body)),
  }),
  uploadImage: async (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/uploads?" + cq(), { method: "POST", body: form });
  },

  exportTex: (body) => request("/api/export/latex", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify(cb(body)),
  }),
  exportPdf: async (body, filename) => {
    const res = await fetch("/api/export/pdf", {
      method: "POST", headers: JSON_HEADERS, body: JSON.stringify(cb(body)),
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
    return request("/api/ingest?" + cq(), { method: "POST", body: form });
  },
  ingestJobs: () => request("/api/ingest"),
  ingestJob:  (job) => request("/api/ingest/" + job),
  ingestPolish: (job, limit) => request(`/api/ingest/${job}/polish` + (limit ? `?limit=${limit}` : ""),
                                        { method: "POST" }),
  ingestCommit: (job) => request(`/api/ingest/${job}/commit?` + cq(), { method: "POST" }),
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
  drafts: () => request("/api/paper-drafts?" + cq()),
  saveDraft: (body) => request("/api/paper-drafts", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify(cb(body)),
  }),
  deleteDraft: (id) => request("/api/paper-drafts/delete", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ id }),
  }),

  // ---- sharing ----
  sharing: () => request("/api/paper-sharing?" + cq()),
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
