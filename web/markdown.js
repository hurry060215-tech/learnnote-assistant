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
    const kinds = markdownLineKinds(lines);
    const html = [];
    const headingIds = new Map();
    const listStack = [];
    let inCode = false;
    let nestedCodeFence = null;
    const listMatch = line => /^([ \t]*)([-+*]|\d+[.)])\s+(.+)$/.exec(line);
    const indentation = value => value.replace(/\t/g, "    ").length;
    const closeListLevel = () => {
      const list = listStack.pop();
      if (list.itemOpen) html.push("</li>");
      html.push(`</${list.type}>`);
    };
    const closeList = () => {
      while (listStack.length) closeListLevel();
    };
    const renderListItem = match => {
      const indent = indentation(match[1]);
      const type = /^\d/.test(match[2]) ? "ol" : "ul";
      while (listStack.length && indent < listStack.at(-1).indent) closeListLevel();
      if (listStack.length && indent === listStack.at(-1).indent && type !== listStack.at(-1).type) closeListLevel();
      let list = listStack.at(-1);
      if (!list || indent > list.indent) {
        const start = Number.parseInt(match[2], 10);
        const startAttribute = type === "ol" && start !== 1 && Number.isSafeInteger(start) ? ` start="${start}"` : "";
        html.push(`<${type}${startAttribute}>`);
        list = { indent, type, itemOpen: false };
        listStack.push(list);
      }
      if (list.itemOpen) html.push("</li>");
      html.push(`<li>${inlineMarkdown(match[3])}`);
      list.itemOpen = true;
    };

    for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
      const rawLine = lines[lineIndex];
      const line = rawLine.trimEnd();
      const nestedFence = /^([ \t]*)(`{3,}|~{3,})(.*)$/.exec(line);
      if (nestedCodeFence) {
        if (nestedFence && nestedFence[2][0] === nestedCodeFence.marker && nestedFence[2].length >= nestedCodeFence.length && !nestedFence[3].trim()) {
          html.push("</code></pre>");
          nestedCodeFence = null;
          inCode = false;
        } else html.push(`${escapeHtml(rawLine)}\n`);
        continue;
      }
      if (!inCode && listStack.length && nestedFence && indentation(nestedFence[1]) > listStack.at(-1).indent) {
        nestedCodeFence = { marker: nestedFence[2][0], length: nestedFence[2].length };
        inCode = true;
        html.push("<pre><code>");
        continue;
      }
      if (kinds[lineIndex] === "open" || kinds[lineIndex] === "close") {
        closeList();
        if (inCode) html.push("</code></pre>");
        else html.push("<pre><code>");
        inCode = kinds[lineIndex] === "open";
        continue;
      }
      if (inCode) {
        html.push(`${escapeHtml(rawLine)}\n`);
        continue;
      }
      if (!line.trim()) {
        // A blank separator within a loose or nested list does not end its
        // parent item; unrelated following blocks still close the list.
        let nextIndex = lineIndex + 1;
        while (nextIndex < lines.length && !lines[nextIndex].trim()) nextIndex += 1;
        const next = nextIndex < lines.length ? lines[nextIndex] : "";
        const nextItem = listMatch(next);
        const continuesList = listStack.length && nextIndex < lines.length && (kinds[nextIndex] === "prose" || kinds[nextIndex] === "open") &&
          (nextItem ? indentation(nextItem[1]) >= listStack[0].indent : indentation((/^([ \t]*)/.exec(next) || [])[1] || "") > listStack.at(-1).indent);
        if (!continuesList) closeList();
        lineIndex = nextIndex - 1;
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
        else html.push(`<p class="external-image">${inlineMarkdown(line.replace(/^!/, "外部图片："))}</p>`);
        continue;
      }
      const heading = /^(#{1,6})\s+(.+)$/.exec(line);
      if (heading) {
        closeList();
        const level = heading[1].length;
        const id = noteHeadingId(heading[2], headingIds);
        html.push(`<h${level} id="${escapeHtml(id)}">${inlineMarkdown(heading[2])}</h${level}>`);
        continue;
      }
      const item = listMatch(line);
      if (item) {
        renderListItem(item);
        continue;
      }
      if (listStack.length && indentation((/^([ \t]*)/.exec(line) || [])[1] || "") > listStack.at(-1).indent) {
        html.push(`<p>${inlineMarkdown(line.trim())}</p>`);
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
    if (inCode) html.push("</code></pre>");
    closeList();
    return html.join("");
  }

  function normalizedTitle(value) {
    return plainHeadingText(value)
      .replace(/[\s\u3000]+/g, "")
      .replace(/[：:|｜·•—–\-_]/g, "")
      .toLocaleLowerCase();
  }

  function markdownLineKinds(lines) {
    let marker = "", length = 0;
    return lines.map(line => {
      const fence = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
      if (!marker && fence) { marker = fence[1][0]; length = fence[1].length; return "open"; }
      if (marker && fence && fence[1][0] === marker && fence[1].length >= length && !fence[2].trim()) { marker = ""; return "close"; }
      return marker ? "code" : "prose";
    });
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
    const kinds = markdownLineKinds(lines);
    const cleaned = [];
    for (let index = 0; index < lines.length; index += 1) {
      if (kinds[index] !== "prose" || !/^\s*-\s*Page context:\s*captured from the current browser page\b/i.test(lines[index])) {
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
    const cleanedKinds = markdownLineKinds(cleaned);
    for (const [index, line] of cleaned.entries()) {
      if (cleanedKinds[index] === "prose" && isRule(line) && isRule(compact.at(-1))) continue;
      compact.push(line);
    }
    return compact.join("\n").trim();
  }

  function noteOutline(markdown, limit = 12) {
    const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
    const kinds = markdownLineKinds(lines);
    const headingIds = new Map();
    const headings = [];
    for (const [index, rawLine] of lines.entries()) {
      const line = rawLine.trimEnd();
      if (kinds[index] !== "prose") continue;
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
