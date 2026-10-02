// The right-hand panel: whatever an answer rests on, shown at its source.

import { api } from "./api.js";
import { citeTarget } from "./cite.js";
import { chip } from "./render.js";
import { html, raw, mount, $, $$ } from "./dom.js";
import { SheetViewer } from "./sheet.js";
import { ModelViewer, modelNotes } from "./model.js";

const FIELD_LABELS = { title: "Title", note: "Note", material: "Material", weight: "Weight [g]", date: "Date", scale: "Scale", sheet: "Sheet" };
// BOM columns are shown as the CSV writes them, typos included, so a reader can find them in the file.
const BOM_COLUMNS = {
  name: "Name", family: "Part family", type: "Type", material: "Material", amount: "Amount",
  design_status: "Design", order_status: "Order", vv_status: "V&V", notes: "Notes", design_intent: "Design Intend",
  interface_with: "Interface with", datasheet: "Datasheet", supplier: "Supplier", supplier_order: "Supplier Order",
  product_name: "Product name", link: "Link", unit_cost: "Cost", total_cost: "Total cost",
};
const KIND_TITLES = { stated: "Stated in the BOM", diagram: "From the system diagrams", inferred: "Inferred from matching fits" };
const DIAGRAM_TITLES = { Zaxis_legend: "Z-axis diagram", RecoaterLegend: "Recoater diagram", PowderLegend: "Powder diagram" };
const EMPTY_VALUE = { blank: "blank on the sheet", disputed: "readers disagree", illegible: "unreadable" };

export class EvidencePanel {
  constructor(root, { navigate }) {
    this.root = root;
    this.navigate = navigate;
    this.state = { part: null, tab: "sheet", sheet: 1, marks: [], focus: null, rows: [], cites: new Set() };
    root.addEventListener("click", (e) => this.click(e));
    this.empty();
  }

  empty() {
    this.state.part = null;
    mount(this.root, html`<div class="panel-empty">
      <p>Ask about a part and its drawing opens here, with the regions the answer cites marked on the sheet.</p>
      <p>Click a citation to jump to it. Scroll to zoom, drag to pan, double-click to fit.</p></div>`);
  }

  // --- opening things ---------------------------------------------------------

  async openAttachment(attachment, cites = []) {
    this.state.cites = new Set(cites);
    if (attachment.type === "drawing") {
      return this.openPart(attachment.ref, { sheet: attachment.sheet, marks: attachment.highlights, focus: attachment.highlights[0]?.cite });
    }
    if (attachment.type === "bom_row") return this.openPart(`BOM.${attachment.row}`, { tab: "bom" });
  }

  async openCite(id) {
    const target = citeTarget(id);
    const evidence = await api.evidence(id).catch(() => null);
    if (!evidence) return;
    if (target.kind === "diagram") return this.openDiagram(target.name, id, evidence);
    if (target.kind === "drawing") {
      const mark = evidence.source.bbox ? { cite: id, sheet: evidence.source.page, bbox: evidence.source.bbox } : null;
      const marks = this.state.part?.ref === target.ref ? [...this.state.marks] : [];
      if (mark && !marks.some((m) => m.cite === id)) marks.push(mark);
      const tab = evidence.field === "bom_link" ? "bom" : "sheet";
      return this.openPart(target.ref, { tab, sheet: evidence.source.page || 1, marks, focus: id });
    }
    if (target.kind === "bom") {
      this.state.cites = new Set([...this.state.cites, id]);
      return this.openPart(`BOM.${target.row}`, { tab: "bom", focus: id });
    }
  }

  async openPart(ref, { tab = "sheet", sheet = 1, marks = [], focus = null } = {}) {
    const part = await api.part(ref);
    const sameView = this.state.part?.ref === part.ref && this.state.part !== null;
    Object.assign(this.state, { part, tab: part.drawing ? tab : "bom", sheet, marks, focus });
    this.root.classList.add("open");
    if (!sameView) this.navigate(`/part/${part.ref}`, { replace: true });
    this.render();
  }

  async openDiagram(name, id, evidence) {
    const src = `/diagrams/${name}.png`;
    const size = await imageSize(src);
    this.state.part = null;
    mount(this.root, html`
      <div class="panel-head">
        <div class="title"><span class="id">${name}.png</span><h2>${DIAGRAM_TITLES[name] || name}</h2><button class="close" data-close>Close</button></div>
        <div class="facts">System diagram from the upstream repository. Relations read off it were transcribed by a person.</div>
        <div class="tabs"><button class="current">Diagram</button></div>
      </div>
      <div class="panel-body"><div class="viewer"></div>
        <div class="panel-section"><table class="facts"><tr><th>Label</th><td>${evidence.value}</td></tr><tr><th>Source</th><td>${raw(chip(id, evidence))}</td></tr></table></div>
      </div>`);
    const viewer = new SheetViewer($(".viewer", this.root));
    viewer.show({ src, ...size, marks: [{ cite: id, bbox: evidence.source.bbox }], focus: id, caption: "Diagram image, pixel coordinates" });
  }

  // --- rendering --------------------------------------------------------------

  render() {
    const { part, tab } = this.state;
    const drawing = part.drawing;
    const rows = (part.bom || []).map((r) => r.row);
    const facts = drawing
      ? [drawing.subsystem, drawing.scan ? `scanned sheet (${drawing.degradation})` : "clean sheet",
         rows.length ? `BOM row${rows.length > 1 ? "s" : ""} ${rows.join(", ")} (${part.bom_link.status})` : "no BOM row"]
      : [`BOM row ${rows[0]}`, "no supplied drawing"];
    const tabs = [["sheet", "Sheet", !drawing], ["model", "Sheet + 3D", !part.model_3d], ["bom", "BOM", !rows.length], ["relations", "Relations", false]];

    mount(this.root, html`
      <div class="panel-head">
        <div class="title"><span class="id">${part.ref}</span><h2>${part.name}</h2><button class="close" data-close>Close</button></div>
        <div class="facts">${facts.join(" · ")}</div>
        <div class="tabs">${tabs.map(([key, label, disabled]) =>
          html`<button data-tab="${key}" class="${key === tab ? "current" : ""}" ${disabled ? raw("disabled") : ""}>${label}</button>`)}</div>
      </div>
      <div class="panel-body"></div>`);

    const body = $(".panel-body", this.root);
    if (tab === "sheet") this.renderSheet(body);
    if (tab === "model") this.renderModel(body);
    if (tab === "bom") this.renderBom(body);
    if (tab === "relations") this.renderRelations(body);
  }

  renderSheet(body) {
    const { part, sheet, marks, focus } = this.state;
    const drawing = part.drawing;
    const page = drawing.sheets[sheet - 1];
    const meta = this.sheetMeta(part.ref, sheet);

    mount(body, html`
      <div class="viewer"></div>
      ${part.attention?.length ? html`<div class="panel-section"><h3>Conflicts and caveats</h3><ul class="attention">${part.attention.map((a) =>
        html`<li>${a.text} ${raw(a.cites.map((c) => chip(c)).join(""))}</li>`)}</ul></div>` : ""}
      <div class="panel-section"><h3>Title block${drawing.sheets.length > 1 ? `, sheet ${sheet} of ${drawing.sheets.length}` : ""}</h3>
        <table class="facts">${Object.entries(page.title_block).map(([field, f]) => html`
          <tr class="${f.cite ? "clickable" : ""} ${f.cite && f.cite === focus ? "hit" : ""}" data-focus="${f.cite || ""}">
            <th>${FIELD_LABELS[field]}</th>
            <td class="value">${f.value || html`<span class="muted">${EMPTY_VALUE[f.status] || "not read"}</span>`}${f.placeholder ? html` <span class="muted">(template placeholder)</span>` : ""}</td>
            <td><span class="status ${statusClass(f.status)}">${reading(f)}</span></td>
          </tr>`)}</table></div>
      <div class="panel-section"><h3>Callouts</h3>
        <table class="facts">${page.callouts.map((c) => html`
          <tr class="clickable ${c.cite === focus ? "hit" : ""}" data-focus="${c.cite}">
            <td class="mono">${c.text}</td>
            <td class="muted">${c.kind}${c.fit_check ? html` <span class="status conflict">failed ISO 286 check</span>` : ""}${
              c.corrected ? html` <span class="status corrected">corrected, ${c.corrected.by}, was ${c.corrected.was}</span>` : ""}</td>
            <td class="muted">${c.read_by === "pdf-text" ? "" : c.read_by}${c.confirmed_by_ocr ? " + ocr" : ""}</td>
          </tr>`)}</table></div>`);

    if (drawing.sheets.length > 1) {
      const tools = $(".viewer", body);
      this.viewer = new SheetViewer(tools, { onMark: (cite) => this.openCite(cite) });
      const select = document.createElement("select");
      select.innerHTML = drawing.sheets.map((_, i) => `<option value="${i + 1}" ${i + 1 === sheet ? "selected" : ""}>Sheet ${i + 1}</option>`).join("");
      select.addEventListener("change", () => { this.state.sheet = Number(select.value); this.render(); });
      $(".viewer-tools", tools).prepend(select);
    } else {
      this.viewer = new SheetViewer($(".viewer", body), { onMark: (cite) => this.openCite(cite) });
    }
    this.viewer.show({
      src: `/kb/${meta.image}`,
      width: meta.width,
      height: meta.height,
      marks: marks.filter((m) => (m.sheet || 1) === sheet),
      focus,
      caption: drawing.scan ? "Scan as supplied. Regions are positions found by OCR, approximate" : "",
    });
  }

  // The sheet and the model side by side. Every dimension the model was built from is marked on
  // the sheet where it was read; pointing at either side, or at the table, lights up the other two.
  async renderModel(body) {
    const model = (await api.models())[this.state.part.ref];
    const meta = this.sheetMeta(this.state.part.ref, 1);
    body.classList.add("linked-body");  // the viewers stay in view; only the notes below them scroll
    mount(body, html`
      <div class="linked"><div class="viewer"></div><div class="viewer model"></div></div>
      <div class="panel-section model-notes">${modelNotes(model)}</div>`);

    // A sheet region can hold several dimensions (one hole callout gives a diameter, a counterbore and its depth).
    const regionOf = model.dimensions.map((d) => (d.region ? d.cite || "measured" : null));
    const marks = [];
    model.dimensions.forEach((d, i) => {
      const key = regionOf[i];
      if (!key || marks.some((m) => m.cite === key)) return;
      const names = model.dimensions.filter((_, j) => regionOf[j] === key).map((x) => x.name);
      marks.push({ cite: key, bbox: d.region, title: `${d.how === "measured" ? "Measured here: " : ""}${names.join(", ")}` });
    });

    let pinned = new Set();
    const rows = [...body.querySelectorAll(".dims-table tr[data-dim]")];
    const light = (dims) => {
      const keys = new Set([...dims].map((i) => regionOf[i]).filter(Boolean));
      sheet.highlight(keys);
      viewer.highlight(dims);
      rows.forEach((r) => r.classList.toggle("hit", dims.has(Number(r.dataset.dim))));
    };
    const hover = (dims) => light(dims ?? pinned);
    const pin = (dims, { zoom = false } = {}) => {
      const same = dims.size === pinned.size && [...dims].every((i) => pinned.has(i));
      pinned = same ? new Set() : dims;
      light(pinned);
      const region = [...pinned].map((i) => model.dimensions[i].region).find(Boolean);
      if (zoom && region) sheet.zoomTo(region);
      if (pinned.size) viewer.focus(pinned);
    };
    const inRegion = (key) => new Set(regionOf.flatMap((k, i) => (k === key ? [i] : [])));

    const [left, right] = body.querySelectorAll(".linked .viewer");
    const sheet = new SheetViewer(left, {
      onHover: (key) => hover(key ? inRegion(key) : null),
      onMark: (key) => pin(inRegion(key)),
    });
    const viewer = new ModelViewer(right, {
      onHover: (i) => hover(i === null ? null : new Set([i])),
      onPick: (i) => pin(new Set([i]), { zoom: true }),
    });
    // Open on the views the dimensions were read from: their callouts, with room for the geometry around them.
    const all = marks.map((m) => m.bbox), room = meta.width * 0.1;
    sheet.show({
      src: `/kb/${meta.image}`, width: meta.width, height: meta.height, marks,
      frame: [Math.min(...all.map((b) => b[0])) - room, Math.min(...all.map((b) => b[1])) - room,
              Math.max(...all.map((b) => b[2])) + room, Math.max(...all.map((b) => b[3])) + room],
    });
    await viewer.show(model);

    const unpin = (e) => {
      if (!body.isConnected) return document.removeEventListener("keydown", unpin);
      if (e.key === "Escape" && pinned.size && !document.querySelector("dialog[open]")) pin(pinned);
    };
    document.addEventListener("keydown", unpin);

    for (const row of rows) {
      const dims = new Set([Number(row.dataset.dim)]);
      row.addEventListener("pointerenter", () => hover(dims));
      row.addEventListener("pointerleave", () => hover(null));
      row.addEventListener("click", (e) => { if (!e.target.closest("[data-cite]")) pin(dims, { zoom: true }); });
    }
  }

  renderBom(body) {
    const { part, focus, cites } = this.state;
    mount(body, html`${part.bom.map((row) => html`
      <div class="panel-section">
        <h3>BOM row ${row.row} · ${row.cells.name?.value || ""}</h3>
        ${part.bom_link ? html`<p class="muted" style="margin:0 0 10px">Link ${part.bom_link.status}: ${part.bom_link.basis} ${raw(chip(part.bom_link.cite, { label: "curation/links.csv", value: part.bom_link.status }))}</p>` : ""}
        <table class="facts">${Object.entries(BOM_COLUMNS).filter(([f]) => row.cells[f]).map(([f, column]) => {
          const cell = row.cells[f];
          return html`<tr class="${cell.cite === focus || cites.has(cell.cite) ? "hit" : ""}">
            <th>${column}</th><td class="value">${cellText(f, cell)}${cell.corrected ? html` <span class="status corrected">corrected, was ${cell.corrected.was}</span>` : ""}</td><td>${raw(chip(cell.cite, { label: column, value: cell.value }))}</td></tr>`;
        })}</table>
        ${row.drawings.length > 1 ? html`<p class="muted">Also documented by ${row.drawings.filter((d) => d !== part.ref).join(", ")}.</p>` : ""}
      </div>`)}
      <div class="panel-section muted">Supplier, price and order data are a BOM snapshot, not current availability.</div>`);
  }

  renderRelations(body) {
    const groups = {};
    for (const r of this.state.part.relations || []) (groups[r.kind] ||= []).push(r);
    if (!Object.keys(groups).length) return mount(body, html`<div class="panel-section muted">No relations recorded for this part.</div>`);
    mount(body, html`<div class="panel-section">${Object.entries(groups).map(([kind, items]) => html`
      <div class="relation-kind"><h3>${KIND_TITLES[kind]}</h3><ul class="relations">${items.map((r) => html`
        <li>${r.relation} <a href="/part/${r.other}" data-part="${r.other}">${r.other_name}</a> <span class="mono muted">${r.other}</span>
          ${raw(r.cites.map((c) => chip(c)).join(""))}
          ${r.note && r.note !== "Label text." ? html`<div class="muted">${r.note}</div>` : ""}</li>`)}</ul></div>`)}</div>`);
  }

  sheetMeta(ref, sheet) {
    return this.drawings?.[ref]?.sheets[sheet - 1];
  }

  // --- events -----------------------------------------------------------------

  click(e) {
    const tab = e.target.closest("[data-tab]");
    if (tab && !tab.disabled) { this.state.tab = tab.dataset.tab; return this.render(); }
    const cite = e.target.closest("[data-cite]");
    if (cite && !cite.closest(".viewer")) return this.openCite(cite.dataset.cite);  // a viewer handles its own marks
    const row = e.target.closest("tr[data-focus]");
    if (row?.dataset.focus) return this.openCite(row.dataset.focus);
    const link = e.target.closest("[data-part]");
    if (link) { e.preventDefault(); return this.openPart(link.dataset.part); }
    if (e.target.closest("[data-close]")) this.root.classList.remove("open");
  }
}

function statusClass(status) {
  return { "single reader": "single" }[status] || status;
}

function reading(f) {
  const by = (method) => f.readings?.find((r) => r.method === method);
  switch (f.status) {
    case "exact": return "text layer";
    case "confirmed": return "OCR and vision agree";
    case "single reader": return `${f.readings?.find((r) => r.cite === f.cite)?.method || "one reader"} only`;
    case "disputed": return `OCR “${by("ocr")?.value || ""}”, vision “${by("vision")?.value || ""}”`;
    case "corrected": return `${f.corrected.by}, was “${f.corrected.was}”`;
    case "blank": return "blank";
    default: return "unreadable";
  }
}

function cellText(field, cell) {
  if (field === "datasheet" && cell.parsed?.files) {
    return `${cell.parsed.files.join(", ")} (attachment link expired ${cell.parsed.url_expired_on.join(", ")})`;
  }
  return cell.value;
}

function imageSize(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = reject;
    img.src = src;
  });
}
