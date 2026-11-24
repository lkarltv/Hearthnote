const inlinePattern = /\\([\\\x60*_[\]#>|~])|(\x60+)(.+?)\2|\[\[([^\]\n]+)\]\]|\[([^\]\n]+)\]\(([^)\n]+)\)|(\*\*|__|~~|\*|_)(?=\S)(.+?)\7/g;
const listPattern = /^\s*(?:(\d+)[.)]|[-+*])\s+(.*)$/;
const headingPattern = /^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/;
const fencePattern = /^\s{0,3}(\x60{3,}|~{3,})(.*)$/;
const rulePattern = /^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$/;

function appendInline(parent, text, depth = 0) {
  if (depth >= 5) {
    parent.append(text);
    return;
  }
  let end = 0;
  for (const match of text.matchAll(inlinePattern)) {
    parent.append(text.slice(end, match.index));
    end = match.index + match[0].length;
    const [, escaped, codeFence, code, wiki, label, url, format, content] = match;
    if (escaped) {
      parent.append(escaped);
    } else if (codeFence) {
      const element = document.createElement("code");
      element.textContent = code;
      parent.append(element);
    } else if (wiki) {
      parent.append(wiki.split("|").at(-1));
    } else if (label) {
      let target;
      try {
        target = new URL(url.trim());
      } catch {
        parent.append(label);
        continue;
      }
      if (!["https:", "http:", "mailto:"].includes(target.protocol)) {
        parent.append(label);
        continue;
      }
      const element = document.createElement("a");
      element.href = target.href;
      element.target = "_blank";
      element.rel = "noopener noreferrer";
      appendInline(element, label, depth + 1);
      parent.append(element);
    } else if (format) {
      const tag = format === "~~" ? "del" : format.length === 2 ? "strong" : "em";
      const element = document.createElement(tag);
      appendInline(element, content, depth + 1);
      parent.append(element);
    }
  }
  parent.append(text.slice(end));
}

function cells(line) {
  return line.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((cell) => cell.trim());
}

function isTable(lines, index) {
  const divider = lines[index + 1];
  return lines[index].includes("|") && divider?.includes("|")
    && cells(divider).every((cell) => /^:?-{3,}:?$/.test(cell));
}

function startsBlock(lines, index) {
  const line = lines[index];
  return !line.trim() || headingPattern.test(line) || fencePattern.test(line)
    || rulePattern.test(line) || listPattern.test(line) || /^\s*>/.test(line) || isTable(lines, index);
}

function renderBlocks(parent, lines, depth = 0) {
  for (let index = 0; index < lines.length;) {
    const line = lines[index++];
    if (!line.trim()) continue;

    const fence = line.match(fencePattern);
    const heading = line.match(headingPattern);
    const list = line.match(listPattern);
    if (fence) {
      const contents = [];
      const close = new RegExp("^[ ]{0,3}" + fence[1][0] + "{" + fence[1].length + ",}\\s*$");
      while (index < lines.length && !close.test(lines[index])) contents.push(lines[index++]);
      if (index < lines.length) index++;
      const block = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = contents.join("\n");
      block.append(code);
      parent.append(block);
    } else if (heading) {
      const element = document.createElement("h" + Math.min(6, heading[1].length + 2));
      appendInline(element, heading[2]);
      parent.append(element);
    } else if (rulePattern.test(line)) {
      parent.append(document.createElement("hr"));
    } else if (list) {
      const ordered = Boolean(list[1]);
      const element = document.createElement(ordered ? "ol" : "ul");
      if (ordered) element.start = Number(list[1]);
      let item = list;
      while (item && Boolean(item[1]) === ordered) {
        const li = document.createElement("li");
        const task = item[2].match(/^\[([ xX])\]\s+(.*)$/);
        if (task) {
          const check = document.createElement("input");
          check.type = "checkbox";
          check.checked = task[1] !== " ";
          check.disabled = true;
          li.className = "task-item";
          li.append(check);
          appendInline(li, task[2]);
        } else {
          appendInline(li, item[2]);
        }
        element.append(li);
        item = lines[index]?.match(listPattern);
        if (item && Boolean(item[1]) === ordered) index++;
      }
      parent.append(element);
    } else if (/^\s*>/.test(line) && depth < 8) {
      const block = document.createElement("blockquote");
      const text = [line.replace(/^\s*>\s?/, "")];
      while (index < lines.length && /^\s*>/.test(lines[index])) {
        text.push(lines[index++].replace(/^\s*>\s?/, ""));
      }
      renderBlocks(block, text, depth + 1);
      parent.append(block);
    } else if (isTable(lines, index - 1)) {
      const wrap = document.createElement("div");
      wrap.className = "material-table";
      const table = document.createElement("table");
      const headers = cells(line);
      const head = table.createTHead().insertRow();
      for (const header of headers) {
        const cell = document.createElement("th");
        cell.scope = "col";
        appendInline(cell, header);
        head.append(cell);
      }
      index++;
      const body = table.createTBody();
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        const values = cells(lines[index++]);
        const row = body.insertRow();
        headers.forEach((_, column) => appendInline(row.insertCell(), values[column] || ""));
      }
      wrap.append(table);
      parent.append(wrap);
    } else {
      const element = document.createElement("p");
      const text = [line];
      while (index < lines.length && !startsBlock(lines, index)) text.push(lines[index++]);
      appendInline(element, text.join("\n"));
      parent.append(element);
    }
  }
}

export function renderMarkdown(parent, content) {
  const lines = content.replace(/^\uFEFF/, "").split(/\r?\n/);
  if (lines[0] === "---") {
    const end = lines.findIndex((line, index) => index > 0 && line === "---");
    if (end > 0 && lines.slice(1, end).some((line) => /^[\w-]+:\s/.test(line))) lines.splice(0, end + 1);
  }
  parent.replaceChildren();
  renderBlocks(parent, lines);
  if (!parent.childElementCount) {
    const empty = document.createElement("p");
    empty.textContent = "This material is empty.";
    parent.append(empty);
  }
}
