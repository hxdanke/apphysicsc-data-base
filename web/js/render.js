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

function escapeAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;")
              .replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function katexReady() {
  return typeof window !== "undefined" && typeof window.katex !== "undefined"
    && typeof window.katex.renderToString === "function";
}

/** Render one maths expression (source *without* delimiters). */
function renderMath(src, display) {
  const tex = String(src).trim();
  if (!tex) return "";
  if (!katexReady()) {
    // KaTeX not available yet: show the source so nothing silently disappears.
    return `<code class="raw">${escapeHtml(tex)}</code>`;
  }
  try {
    return window.katex.renderToString(tex, {
      displayMode: !!display,
      throwOnError: false,
      strict: "ignore",
      output: "html",
    });
  } catch (err) {
    return `<code class="raw">${escapeHtml(tex)}</code>`;
  }
}

/**
 * Locate every maths run in a TeX fragment, with its boundaries, body and the
 * delimiter kind that opened it.  `$$`/`\[`/`\(` are display; single `$` inline.
 *
 * The result drives both rendering (so each formula can carry a data-idx) and
 * the single-formula editor (which replaces the body by index).
 */
export function extractMathRuns(src) {
  const runs = [];
  let i = 0;
  while (i < src.length) {
    const ch = src[i];

    if (ch === "$" && src[i + 1] === "$") {
      const end = src.indexOf("$$", i + 2);
      if (end > i + 1) {
        runs.push({ start: i, end: end + 2, body: src.slice(i + 2, end),
                    delim: "$$", display: true });
        i = end + 2;
        continue;
      }
    }
    if (ch === "\\" && src[i + 1] === "[") {
      const end = src.indexOf("\\]", i + 2);
      if (end > i) {
        runs.push({ start: i, end: end + 2, body: src.slice(i + 2, end),
                    delim: "\\[", display: true });
        i = end + 2;
        continue;
      }
    }
    if (ch === "\\" && src[i + 1] === "(") {
      const end = src.indexOf("\\)", i + 2);
      if (end > i) {
        runs.push({ start: i, end: end + 2, body: src.slice(i + 2, end),
                    delim: "\\(", display: false });
        i = end + 2;
        continue;
      }
    }
    if (ch === "$") {
      const end = src.indexOf("$", i + 1);
      if (end > i + 1) {
        runs.push({ start: i, end: end + 1, body: src.slice(i + 1, end),
                    delim: "$", display: false });
        i = end + 1;
        continue;
      }
    }
    i += 1;
  }
  return runs;
}

/**
 * Replace the body of the idx-th maths run (0-based) with `newBody`, keeping the
 * surrounding delimiters.  Returns null when the index is out of range.
 */
export function replaceMathRun(src, idx, newBody) {
  const runs = extractMathRuns(src);
  if (idx < 0 || idx >= runs.length) return null;
  const r = runs[idx];
  let open, close;
  if (r.delim === "$$") { open = "$$"; close = "$$"; }
  else if (r.delim === "\\[") { open = "\\["; close = "\\]"; }
  else if (r.delim === "\\(") { open = "\\("; close = "\\)"; }
  else { open = "$"; close = "$"; }
  return src.slice(0, r.start) + open + newBody + close + src.slice(r.end);
}

/** Render a TeX fragment: inline $...$, display, images, plain text. */
export function renderLatex(src, fieldKey = "") {
  if (!src) return "";
  src = String(src);

  // Split into image / text chunks so \includegraphics stays intact.
  const chunks = [];
  let last = 0;
  IMG_RE.lastIndex = 0;
  let m;
  while ((m = IMG_RE.exec(src)) !== null) {
    if (m.index > last) chunks.push({ type: "text", text: src.slice(last, m.index) });
    const opts = m[1] || "";
    const wm = opts.match(WIDTH_RE);
    const pct = wm ? Math.min(100, Math.round(parseFloat(wm[1]) * 100)) : null;
    chunks.push({ type: "img", src: m[2], pct });
    last = IMG_RE.lastIndex;
  }
  if (last < src.length) chunks.push({ type: "text", text: src.slice(last) });

  let html = "";
  for (const c of chunks) {
    if (c.type === "img") {
      html += `<img class="qfig" loading="lazy" src="${resolveMedia(c.src)}"` +
              (c.pct ? ` style="width:${c.pct}%"` : "") + ` alt="figure" />`;
    } else {
      html += renderTextRuns(c.text, fieldKey);
    }
  }
  return html;
}

/**
 * Render a text chunk, handing every maths run to KaTeX and wrapping it in a
 * clickable span that carries the raw source (for the single-formula editor).
 * `idxState` keeps a running index across the whole field so the editor can
 * address a formula by its position.
 */
function renderTextRuns(chunk, fieldKey) {
  const runs = extractMathRuns(chunk);
  if (!runs.length) return escapeHtml(chunk);

  let out = "";
  let last = 0;
  let idx = 0;
  for (const r of runs) {
    if (r.start > last) out += escapeHtml(chunk.slice(last, r.start));
    const html = renderMath(r.body, r.display);
    out += `<span class="math" data-field="${escapeAttr(fieldKey)}" ` +
           `data-idx="${idx}" data-tex="${escapeAttr(r.body)}" ` +
           `data-display="${r.display ? 1 : 0}" tabindex="0" ` +
           `title="Click to edit formula">${html}</span>`;
    idx += 1;
    last = r.end;
  }
  if (last < chunk.length) out += escapeHtml(chunk.slice(last));
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
