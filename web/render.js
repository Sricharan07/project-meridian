// Turns an answer into HTML: paragraphs, lists, **bold**, `code`, and [cite] chips.
// A deliberately small subset of markdown; anything else stays as plain escaped text.

import { escape } from "./dom.js";
import { citeLabel } from "./cite.js";

const CITATION = /\[([A-Za-z][\w.:~\-]*(?:\s*[,;]\s*[A-Za-z][\w.:~\-]*)*)\]/g;
const SLOT = /\u0000(\d+)\u0000/g;

export function answerHtml(text, citations = {}) {
  const groups = [];
  const body = text.replace(CITATION, (_, inner) => {
    groups.push(inner.split(/[,;]/).map((s) => s.trim()).filter(Boolean));
    return `\u0000${groups.length - 1}\u0000`;
  });
  return blocks(escape(body))
    .replace(SLOT, (_, i) => chips(groups[Number(i)], citations));
}

// A citation chip. `evidence` (from the API) gives it a tooltip; `missing` marks an id
// the answer cited that does not exist, which the verifier will also have reported.
export function chip(id, evidence = null, { missing = false } = {}) {
  const tip = missing ? "Not a known observation" : evidence ? `${evidence.label}: ${evidence.value || "(blank)"}` : id;
  return `<button class="cite${missing ? " missing" : ""}" data-cite="${escape(id)}" title="${escape(tip)}">${escape(citeLabel(id))}</button>`;
}

function chips(ids, citations) {
  // Long runs ("the nine rows with no recorded cost") collapse so the sentence stays readable.
  const shown = ids.length > 3 ? ids.slice(0, 2) : ids;
  const rest = ids.slice(shown.length);
  let out = shown.map((id) => chip(id, citations[id], { missing: !citations[id] })).join("");
  if (rest.length) out += `<button class="cite more" data-more="${escape(rest.join(","))}">+${rest.length}</button>`;
  return out;
}

function inline(s) {
  return s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
}

function blocks(s) {
  const out = [];
  let list = null;
  let paragraph = [];
  const flush = () => {
    if (paragraph.length) out.push(`<p>${paragraph.map(inline).join("<br>")}</p>`);
    paragraph = [];
  };
  const close = () => {
    if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`);
    list = null;
  };
  for (const line of s.split("\n")) {
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      flush();
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tag !== tag) { close(); list = { tag, items: [] }; }
      list.items.push((bullet || numbered)[1]);
    } else if (!line.trim()) {
      flush();
      close();
    } else {
      close();
      paragraph.push(line);
    }
  }
  flush();
  close();
  return out.join("");
}
