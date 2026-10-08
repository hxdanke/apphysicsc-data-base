const JSON_HEADERS = {"Content-Type": "application/json"};

async function request(url, options = {}) {
  const res = await fetch(url, options);
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
};
