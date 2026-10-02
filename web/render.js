// Turns an answer into HTML: paragraphs, lists, **bold**, `code`, and numbered references.
// A deliberately small subset of markdown; anything else stays as plain escaped text.
//
// Each cited observation gets a number the first time the answer cites it, the way a drawing
// numbers its balloons. The same number marks the region on the sheet, and the source list under
// the answer says what each number is. A reading that the readers dispute, or that failed a
// tolerance check, is numbered in red.

import { escape } from "./dom.js";
import { citeLabel } from "./cite.js";

const CITATION = /\[([A-Za-z][\w.:~\-]*(?:\s*[,;]\s*[A-Za-z][\w.:~\-]*)*)\]/g;
const SLOT = /\u0000(\d+)\u0000/g;
const FIELDS = { title: "Title", note: "Note", material: "Material", weight: "Weight", date: "Date", scale: "Scale",
  sheet: "Sheet", callout: "Callout", bom_link: "Link to BOM", subsystem: "Subsystem", upstream_file: "Upstream file", label: "Label" };
const READERS = { ocr: "OCR", vision: "vision", review: "corrected", web: "web search" };
const DIAGRAMS = { Zaxis_legend: "Z-axis diagram", RecoaterLegend: "Recoater diagram", PowderLegend: "Powder diagram" };

export function answer(text, citations = {}) {
  const refs = new Map();
  const groups = [];
  const body = text.replace(CITATION, (_, inner) => {
    groups.push(inner.split(/[,;]/).map((s) => s.trim()).filter(Boolean));
    return `\u0000${groups.length - 1}\u0000`;
  });
  for (const ids of groups) {
    for (const id of ids) if (!refs.has(id)) refs.set(id, { n: refs.size + 1, id, evidence: citations[id] || null });
  }
  const html = blocks(escape(body)).replace(SLOT, (_, i) => groups[Number(i)].map((id) => ref(refs.get(id))).join(""));
  return { html, refs: [...refs.values()] };
}

// In running text a reference is a button; inside a source row, which is the button, it is a plain mark.
export function ref({ n, id, evidence }, { inline = true } = {}) {
  if (!evidence) return `<span class="ref missing" title="Not a known observation: ${escape(id)}">?</span>`;
  const cls = `ref${isRed(evidence) ? " red" : ""}`;
  if (!inline) return `<span class="${cls}">${n}</span>`;
  return `<button type="button" class="${cls}" data-cite="${escape(id)}" title="${escape(sourceLabel(id, evidence))}">${n}</button>`;
}

export function isRed(evidence) {
  return evidence?.status === "disputed" || Boolean(evidence?.parsed?.fit_check);
}

// How a source reads in a list: "BOM row 30 · Material", "D-011 · Material · OCR".
export function sourceLabel(id, e) {
  if (!e) return citeLabel(id);
  if (e.source?.doc === "BOM") return e.label;
  if (e.source?.doc?.startsWith("diagram:")) return DIAGRAMS[e.source.doc.slice(8)] || "System diagram";
  if (e.method === "web") return `${e.value || "Not identified"} · web search, ${e.parsed.retrieved}`;
  const parts = [e.subject, FIELDS[e.field] || e.field];
  if (READERS[e.method]) parts.push(READERS[e.method]);
  if (e.field === "subsystem") parts.push("manifest");
  return parts.join(" · ");
}

// A citation outside an answer (in the inspector, the review page): quiet until pointed at.
export function chip(id, evidence = null, { missing = false } = {}) {
  const tip = missing ? "Not a known observation" : evidence ? `${evidence.label}: ${evidence.value || "(blank)"}` : id;
  return `<button class="cite${missing ? " missing" : ""}" data-cite="${escape(id)}" title="${escape(tip)}">${escape(citeLabel(id))}</button>`;
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
