/* LaTeX -> HTML, using KaTeX for math and <img> for \includegraphics. */

const IMG_RE = /\\includegraphics\s*(?:\[([^\]]*)\])?\s*\{([^{}]*)\}/g;
const WIDTH_RE = /width\s*=\s*([0-9.]+)\s*\\(?:linewidth|textwidth|columnwidth)/;

export function resolveMedia(path) {
  const p = String(path).replace(/^\.\//, "").replace(/\\/g, "/");
  if (p.startsWith("media/")) return "/" + p;
  return "/api/file?path=" + encodeURIComponent(p);
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function katex(src, display) {
  if (typeof window.katex === "undefined") {
    return `<code class="raw">${escapeHtml(src)}</code>`;
  }
  // PDF-extracted math often has a formula split across two $...$ runs with a
  // missing delimiter between them. Glue such neighbours back together.
  let out = "";
  for (const piece of mergeAdjacentMath(src)) {
    if (piece.math) {
      let html;
      try {
        html = window.katex.renderToString(piece.text, {
          displayMode: display, throwOnError: false,
        });
      } catch (err) {
        html = `<code class="raw">${escapeHtml(piece.text)}</code>`;
      }
      out += html;
    } else {
      out += escapeHtml(piece.text);
    }
  }
  return out;
}

const MERGE_RE = /(?:\$[^$]+\$)+/g;

function mergeAdjacentMath(src) {
  const parts = [];
  let last = 0;
  let m;
  MERGE_RE.lastIndex = 0;
  while ((m = MERGE_RE.exec(src)) !== null) {
    if (m.index > last) parts.push({ math: false, text: src.slice(last, m.index) });
    const body = m[0].split("$").filter(Boolean).join("\\ ");
    parts.push({ math: true, text: body });
    last = MERGE_RE.lastIndex;
  }
  if (last < src.length) parts.push({ math: false, text: src.slice(last) });
  return parts;
}

/** Render a TeX fragment: inline $...$, display \[...\], images, plain text. */
export function renderLatex(src) {
  if (!src) return "";
  src = String(src);
  let out = "";
  let last = 0;
  let m;

  IMG_RE.lastIndex = 0;
  while ((m = IMG_RE.exec(src)) !== null) {
    if (m.index > last) out += renderText(src.slice(last, m.index));
    const opts = m[1] || "";
    const wm = opts.match(WIDTH_RE);
    const pct = wm ? Math.min(100, Math.round(parseFloat(wm[1]) * 100)) : null;
    out += `<img class="qfig" loading="lazy" src="${resolveMedia(m[2])}"` +
           (pct ? ` style="width:${pct}%"` : "") +
           ` alt="figure" />`;
    last = IMG_RE.lastIndex;
  }
  if (last < src.length) out += renderText(src.slice(last));
  return out;
}

function renderText(chunk) {
  let out = "";
  let i = 0;
  while (i < chunk.length) {
    const ch = chunk[i];
    if (ch === "$") {
      const end = chunk.indexOf("$", i + 1);
      if (end > i + 1) {
        // collect every maths run that is directly adjacent, then render once
        let j = end + 1;
        while (chunk[j] === "$") {
          const e2 = chunk.indexOf("$", j + 1);
          if (e2 <= j + 1) break;
          j = e2 + 1;
        }
        out += katex(chunk.slice(i + 1, j).replace(/\$/g, ""), false);
        i = j;
        continue;
      }
    }
    if (ch === "\\" && chunk[i + 1] === "[") {
      const end = chunk.indexOf("\\]", i + 2);
      if (end > i) {
        out += katex(chunk.slice(i + 2, end), true);
        i = end + 2;
        continue;
      }
    }
    out += escapeHtml(ch);
    i += 1;
  }
  return out;
}

/** Short single-line preview for list cards. */
export function plainPreview(q, max = 180) {
  let s = (q.stem || "") + " " + (q.choices || []).map(c => c.text || "").join(" ");
  s = s.replace(IMG_RE, " [figure] ")
       .replace(/\$([^$]*)\$/g, (_, m) => m.replace(/\\mathrm\{([^}]*)\}/g, "$1")
                                          .replace(/\\[a-zA-Z]+/g, " ")
                                          .replace(/[{}]/g, ""))
       .replace(/\s+/g, " ")
       .trim();
  return s.length > max ? s.slice(0, max) + "…" : s;
}
