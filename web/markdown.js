(function installLearnNoteMarkdown(global) {
  "use strict";

  let safeMediaUrl = value => {
    const raw = String(value || "").trim();
    return /^https?:\/\//i.test(raw) || /^\/(?:api|data)\//i.test(raw) ? raw : "";
  };

  const escapeHtml = value => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

  function configure(options = {}) {
    if (typeof options.safeNoteMediaUrl === "function") safeMediaUrl = options.safeNoteMediaUrl;
  }

  function inlineMarkdown(value) {
    return escapeHtml(value)
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/~~([^~]+)~~/g, "<del>$1</del>");
  }

  function plainHeadingText(value) {
    return String(value || "")
      .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/[`*_~#]/g, "")
      .trim();
  }

  function noteHeadingId(value, counts = new Map()) {
    const plain = plainHeadingText(value);
    const slug = plain
      .toLowerCase()
      .replace(/[^\w\u4e00-\u9fff]+/g, "-")
      .replace(/^-+|-+$/g, "") || "section";
    const base = `note-${slug}`;
    const count = counts.get(base) || 0;
    counts.set(base, count + 1);
    return count ? `${base}-${count + 1}` : base;
  }

  function markdownTableCells(line) {
    const trimmed = String(line || "").trim().replace(/^\|/, "").replace(/\|$/, "");
    if (!trimmed.includes("|")) return [];
    return trimmed.split("|").map(cell => cell.trim());
  }

  function markdownTableAlignment(line) {
    const cells = markdownTableCells(line);
    if (!cells.length || cells.some(cell => !/^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")))) return null;
    return cells.map(cell => {
      const value = cell.replace(/\s+/g, "");
      if (value.startsWith(":") && value.endsWith(":")) return "center";
      if (value.endsWith(":")) return "right";
      return "left";
    });
  }

  function markdownTableHtml(header, rows, alignments) {
    const style = index => ` style="text-align:${alignments[index] || "left"}"`;
    return `<div class="markdown-table-wrap"><table><thead><tr>${header.map((cell, index) => `<th${style(index)}>${inlineMarkdown(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${header.map((_, index) => `<td${style(index)}>${inlineMarkdown(row[index] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function markdownToHtml(markdown) {
    const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
    const html = [];
    const headingIds = new Map();
    let listType = "";
    let inCode = false;
    const closeList = () => {
      if (listType) {
        html.push(`</${listType}>`);
        listType = "";
      }
    };

    for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
      const rawLine = lines[lineIndex];
      const line = rawLine.trimEnd();
      if (line.startsWith("```")) {
        closeList();
        if (inCode) html.push("</code></pre>");
        else html.push("<pre><code>");
        inCode = !inCode;
        continue;
      }
      if (inCode) {
        html.push(`${escapeHtml(rawLine)}\n`);
        continue;
      }
      if (!line.trim()) {
        closeList();
        continue;
      }
      if (/^\s*---+\s*$/.test(line)) {
        closeList();
        html.push("<hr>");
        continue;
      }
      const tableHeader = markdownTableCells(line);
      const tableAlignments = lineIndex + 1 < lines.length ? markdownTableAlignment(lines[lineIndex + 1]) : null;
      if (tableHeader.length && tableAlignments && tableAlignments.length === tableHeader.length) {
        closeList();
        const rows = [];
        lineIndex += 2;
        while (lineIndex < lines.length) {
          const cells = markdownTableCells(lines[lineIndex]);
          if (!cells.length) break;
          rows.push(cells);
          lineIndex += 1;
        }
        lineIndex -= 1;
        html.push(markdownTableHtml(tableHeader, rows, tableAlignments));
        continue;
      }
      const image = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(line.trim());
      if (image) {
        closeList();
        const src = safeMediaUrl(image[2]);
        const alt = escapeHtml(image[1] || "frame grid");
        if (src) html.push(`<figure class="note-image-frame"><img src="${src}" alt="${alt}"><figcaption>${alt}</figcaption></figure>`);
        else html.push(`<p>${inlineMarkdown(line)}</p>`);
        continue;
      }
      const heading = /^(#{1,3})\s+(.+)$/.exec(line);
      if (heading) {
        closeList();
        const level = heading[1].length;
        const id = noteHeadingId(heading[2], headingIds);
        html.push(`<h${level} id="${escapeHtml(id)}">${inlineMarkdown(heading[2])}</h${level}>`);
        continue;
      }
      const bullet = /^[-*]\s+(.+)$/.exec(line);
      if (bullet) {
        if (listType !== "ul") {
          closeList();
          html.push("<ul>");
          listType = "ul";
        }
        html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
        continue;
      }
      const numbered = /^\d+\.\s+(.+)$/.exec(line);
      if (numbered) {
        if (listType !== "ol") {
          closeList();
          html.push("<ol>");
          listType = "ol";
        }
        html.push(`<li>${inlineMarkdown(numbered[1])}</li>`);
        continue;
      }
      if (line.startsWith(">")) {
        closeList();
        html.push(`<blockquote>${inlineMarkdown(line.replace(/^>\s?/, ""))}</blockquote>`);
        continue;
      }
      closeList();
      html.push(`<p>${inlineMarkdown(line)}</p>`);
    }
    closeList();
    if (inCode) html.push("</code></pre>");
    return html.join("");
  }

  function normalizedTitle(value) {
    return plainHeadingText(value)
      .replace(/[\s\u3000]+/g, "")
      .replace(/[：:|｜·•—–\-_]/g, "")
      .toLocaleLowerCase();
  }

  function sanitizeNoteMarkdown(markdown, options = {}) {
    const requestedTitle = typeof options === "string" ? options : options?.title;
    const titleKey = normalizedTitle(requestedTitle || "");
    const sourceLines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
    let start = 0;

    // Generated notes occasionally contain YAML front matter. The surrounding
    // task header already owns this metadata, so do not expose raw delimiters to
    // readers. Only treat the opening block as front matter when it contains a
    // key/value pair, which preserves deliberate horizontal rules in the body.
    if (/^\s*---\s*$/.test(sourceLines[0] || "")) {
      const closing = sourceLines.slice(1, 41).findIndex(line => /^\s*---\s*$/.test(line));
      const block = closing >= 0 ? sourceLines.slice(1, closing + 1) : [];
      if (closing >= 0 && block.some(line => /^\s*[\w\u4e00-\u9fff-]+\s*:\s*\S/.test(line))) {
        start = closing + 2;
      }
    }

    const lines = sourceLines.slice(start);
    const cleaned = [];
    for (let index = 0; index < lines.length; index += 1) {
      if (!/^\s*-\s*Page context:\s*captured from the current browser page\b/i.test(lines[index])) {
        cleaned.push(lines[index]);
        continue;
      }
      while (index + 1 < lines.length && /^(?: {2,}|\t)\S/.test(lines[index + 1])) index += 1;
    }

    const isRule = line => /^\s*(?:-{3,}|_{3,}|\*{3,})\s*$/.test(line || "");
    while (cleaned.length && (!cleaned[0].trim() || isRule(cleaned[0]))) cleaned.shift();
    while (cleaned.length && (!cleaned.at(-1).trim() || isRule(cleaned.at(-1)))) cleaned.pop();

    // The result header already renders the task title. Remove repeated leading
    // headings only when they are the same title; chapter headings remain intact.
    while (titleKey && cleaned.length) {
      const heading = /^\s*#{1,2}\s+(.+?)\s*$/.exec(cleaned[0]);
      if (!heading || normalizedTitle(heading[1]) !== titleKey) break;
      cleaned.shift();
      while (cleaned.length && (!cleaned[0].trim() || isRule(cleaned[0]))) cleaned.shift();
    }

    // Collapse accidental repeated separators without flattening intentional
    // section breaks inside the note.
    const compact = [];
    for (const line of cleaned) {
      if (isRule(line) && isRule(compact.at(-1))) continue;
      compact.push(line);
    }
    return compact.join("\n").trim();
  }

  function noteOutline(markdown, limit = 12) {
    const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
    const headingIds = new Map();
    const headings = [];
    let inCode = false;
    for (const rawLine of lines) {
      const line = rawLine.trimEnd();
      if (line.startsWith("```")) {
        inCode = !inCode;
        continue;
      }
      if (inCode) continue;
      const heading = /^(#{1,3})\s+(.+)$/.exec(line);
      if (!heading) continue;
      const text = plainHeadingText(heading[2]);
      if (!text) continue;
      headings.push({ level: heading[1].length, text, id: noteHeadingId(heading[2], headingIds) });
    }
    if (!headings.length) return "";
    return `<section class="note-outline" aria-label="笔记目录">
    <div class="visual-rail-head">
      <strong>笔记目录</strong>
      <span>${headings.length} 节</span>
    </div>
    <div class="note-outline-list">
      ${headings.slice(0, limit).map(heading => `<a class="level-${heading.level}" href="#${escapeHtml(heading.id)}">${escapeHtml(heading.text)}</a>`).join("")}
    </div>
  </section>`;
  }

  global.LearnNoteMarkdown = Object.freeze({
    configure,
    inlineMarkdown,
    markdownToHtml,
    noteHeadingId,
    noteOutline,
    plainHeadingText,
    sanitizeNoteMarkdown
  });
})(typeof globalThis !== "undefined" ? globalThis : window);
