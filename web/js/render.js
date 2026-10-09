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

function katexReady() {
  return typeof window !== "undefined" && typeof window.katex !== "undefined"
    && typeof window.katex.renderToString === "function";
}

/** Render one maths expression (source *without* $ delimiters). */
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

/**
 * Walk a text chunk, handing every maths run to KaTeX and escaping the rest.
 *
 * The PDF extractor often splits one formula into several neighbouring
 * $..$ runs (`$A(\sin\theta -$$ \cos\theta)$`), so adjacent runs are glued
 * back together before rendering.
 */
function renderText(chunk) {
  let out = "";
  let i = 0;
  while (i < chunk.length) {
    const ch = chunk[i];

    // display maths: $$...$$  or  \[...\]
    if (ch === "$" && chunk[i + 1] === "$") {
      const end = chunk.indexOf("$$", i + 2);
      if (end > i + 1) {
        out += renderMath(chunk.slice(i + 2, end), true);
        i = end + 2;
        continue;
      }
    }
    if (ch === "\\" && chunk[i + 1] === "[") {
      const end = chunk.indexOf("\\]", i + 2);
      if (end > i) {
        out += renderMath(chunk.slice(i + 2, end), true);
        i = end + 2;
        continue;
      }
    }
    if (ch === "\\" && chunk[i + 1] === "(") {
      const end = chunk.indexOf("\\)", i + 2);
      if (end > i) {
        out += renderMath(chunk.slice(i + 2, end), false);
        i = end + 2;
        continue;
      }
    }

    // inline maths: one or more adjacent $...$ runs
    if (ch === "$") {
      const bodies = [];
      let j = i;
      while (chunk[j] === "$") {
        const end = chunk.indexOf("$", j + 1);
        if (end <= j + 1) break;
        bodies.push(chunk.slice(j + 1, end));
        j = end + 1;
      }
      if (bodies.length) {
        out += renderMath(bodies.join(" "), false);
        i = j;
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
