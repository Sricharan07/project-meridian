// The right-hand side: whatever an answer rests on, shown at its source. A header names the part,
// the stage shows the sheet (or the sheet beside its 3D model), and the inspector lists what was read
// off it and what needs a second look.

import { api } from "./api.js";
import { citeTarget } from "./cite.js";
import { chip, isRed } from "./render.js";
import { icon, mark } from "./icons.js";
import { html, raw, mount, slide, escape, $, $$ } from "./dom.js";
import { SheetViewer } from "./sheet.js";
import { ModelViewer, modelNotes } from "./model.js";

const FIELD_LABELS = { title: "Title", note: "Note", material: "Material", weight: "Weight", date: "Date", scale: "Scale", sheet: "Sheet" };
// BOM columns are shown as the CSV writes them, typos included, so a reader can find them in the file.
const BOM_COLUMNS = {
  name: "Name", family: "Part family", type: "Type", material: "Material", amount: "Amount",
  design_status: "Design", order_status: "Order", vv_status: "V&V", notes: "Notes", design_intent: "Design Intend",
  interface_with: "Interface with", datasheet: "Datasheet", supplier: "Supplier", supplier_order: "Supplier Order",
  product_name: "Product name", link: "Link", unit_cost: "Cost", total_cost: "Total cost",
};
const KIND_TITLES = { stated: "Stated in the BOM", diagram: "From the system diagrams", inferred: "Inferred from matching fits" };
const DIAGRAM_TITLES = { Zaxis_legend: "Z-axis diagram", RecoaterLegend: "Recoater diagram", PowderLegend: "Powder diagram" };
const TABS = [["sheet", "Sheet", "sheet"], ["model", "3D", "cube"], ["bom", "BOM", null], ["suppliers", "Suppliers", null], ["relations", "Relations", null]];
const MATCH = { "part number confirmed": ["agree", "Same part no."], "found by the search": ["single", "Found by search"], equivalent: ["info", "Equivalent"] };
const CHECK = { pass: "agree", fail: "warn", unknown: "blank" };

export class EvidencePanel {
  constructor(root, { navigate }) {
    this.root = root;
    this.navigate = navigate;
    this.state = { part: null, tab: "sheet", sheet: 1, marks: [], focus: null, refs: new Map() };
    root.addEventListener("click", (e) => this.click(e));
    root.addEventListener("change", (e) => {
      if (!e.target.matches("[data-sheet]")) return;
      this.state.sheet = Number(e.target.value);
      this.render();
    });
  }

  empty() {
    this.state.part = null;
    this.viewer = null;
    this.root.dataset.showing = "";
    mount(this.root, html`<div class="empty-wrap"><div class="empty-stage"><p>
      <strong>Drawings open here</strong>Ask about a part and its sheet opens with every cited value marked.
      Press ${raw("<kbd>⌘K</kbd>")} to open any drawing directly.</p></div></div>`);
  }

  refresh() {
    if (this.state.part) this.render();
  }

  // --- opening things ----------------------------------------------------------------------

  // `refs` are an answer's numbered references, so the sheet can carry the same numbers.
  async openAttachment(attachment, refs = []) {
    this.state.refs = new Map(refs.filter((r) => r.evidence).map((r) => [r.id, { n: r.n, red: isRed(r.evidence) }]));
    if (attachment.type === "drawing") {
      return this.openPart(attachment.ref, { sheet: attachment.sheet, marks: attachment.highlights, focus: attachment.highlights[0]?.cite, keepRefs: true });
    }
    if (attachment.type === "bom_row") return this.openPart(`BOM.${attachment.row}`, { tab: "bom", keepRefs: true });
    if (attachment.type === "suppliers") return this.openPart(attachment.ref, { tab: "suppliers", keepRefs: true });
  }

  async openCite(id, refs) {
    if (refs) this.state.refs = new Map(refs.filter((r) => r.evidence).map((r) => [r.id, { n: r.n, red: isRed(r.evidence) }]));
    const target = citeTarget(id);
    const evidence = await api.evidence(id).catch(() => null);
    if (!evidence) return;
    if (target.kind === "diagram") return this.openDiagram(target.name, id, evidence);
    if (target.kind === "drawing") {
      const mark = evidence.source.bbox ? { cite: id, sheet: evidence.source.page, bbox: evidence.source.bbox, red: isRed(evidence) } : null;
      const marks = this.state.part?.ref === target.ref ? [...this.state.marks] : [];
      if (mark && !marks.some((m) => m.cite === id)) marks.push(mark);
      const tab = evidence.field === "bom_link" ? "bom" : "sheet";
      const page = evidence.source.page || 1;
      if (this.viewer && tab === "sheet" && this.state.tab === "sheet" && this.state.part?.ref === target.ref && this.state.sheet === page) {
        // Already on this sheet: add the mark and travel to it, keeping the inspector where it is.
        Object.assign(this.state, { marks, focus: id });
        this.viewer.setMarks(this.sheetMarks(), id);
        $$(".inspector [data-focus]", this.root).forEach((row) => row.classList.toggle("lit", row.dataset.focus === id));
        if (!this.viewer.focus(id)) $(`.inspector [data-focus="${CSS.escape(id)}"]`, this.root)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
        return;
      }
      return this.openPart(target.ref, { tab, sheet: evidence.source.page || 1, marks, focus: id, keepRefs: true });
    }
    if (evidence.method === "web") {
      // A supplier suggestion belongs to a BOM row; a maker belongs to whichever part asked about it.
      const ref = target.kind === "bom" ? `BOM.${target.row}` : this.state.part?.ref;
      return ref ? this.openPart(ref, { tab: "suppliers", focus: id, keepRefs: true }) : window.open(evidence.parsed.url, "_blank", "noopener");
    }
    if (target.kind === "bom") return this.openPart(`BOM.${target.row}`, { tab: "bom", focus: id, keepRefs: true });
  }

  async openPart(ref, { tab = "sheet", sheet = 1, marks = [], focus = null, keepRefs = false } = {}) {
    const part = await api.part(ref);
    const same = this.state.part?.ref === part.ref;
    if (!keepRefs && !same) this.state.refs = new Map();
    Object.assign(this.state, { part, tab: part.drawing || !["sheet", "model"].includes(tab) ? tab : "bom", sheet, marks, focus });
    this.root.classList.add("open");
    if (!same) this.navigate(`/part/${part.ref}`, { replace: true });
    this.render();
  }

  async openDiagram(name, id, evidence) {
    const src = `/diagrams/${name}.png`;
    const size = await imageSize(src);
    this.state.part = null;
    this.root.dataset.showing = "";
    mount(this.root, html`
      <div class="panel-head">
        <div><div class="part-title"><span class="id">${name}.png</span><h2>${DIAGRAM_TITLES[name] || name}</h2></div>
          <div class="part-facts">System diagram from the upstream repository · relations transcribed by a person</div></div>
        <div class="tabs"><button class="current">Diagram</button><span class="tab-indicator"></span></div>
      </div>
      <div class="panel-body"><div class="stage"><div class="viewer"></div></div>
        <aside class="inspector"><div class="group"><h3 class="group-title">Label</h3>
          <div class="rows"><div class="row wide"><span class="v">${evidence.value}</span><span>${raw(mark("info"))}</span></div></div></div>
          <p class="note">${raw(chip(id, evidence))}</p></aside></div>`);
    slide($(".tab-indicator", this.root), $(".tabs .current", this.root));
    this.viewer = new SheetViewer($(".viewer", this.root));
    this.viewer.show({ src, ...size, marks: [{ cite: id, bbox: evidence.source.bbox }], focus: id });
  }

  // Point at a reference in the chat: light its mark, and after a moment bring it into view.
  preview(id) {
    clearTimeout(this.previewing);
    if (!this.viewer || this.state.tab !== "sheet") return;
    this.viewer.highlight(new Set(id ? [id] : []));
    $$(".inspector [data-focus]", this.root).forEach((row) => row.classList.toggle("lit", Boolean(id) && row.dataset.focus === id));
    if (id && this.viewer.has(id)) this.previewing = setTimeout(() => this.viewer.focus(id), 160);
  }

  // --- rendering ---------------------------------------------------------------------------

  render() {
    const { part, tab } = this.state;
    if (this.root.dataset.showing !== part.ref || !$(".panel-head", this.root)) this.renderHead();
    for (const button of $$(".tabs [data-tab]", this.root)) button.classList.toggle("current", button.dataset.tab === tab);
    slide($(".tab-indicator", this.root), $(".tabs .current", this.root));

    const body = $(".panel-body", this.root);
    body.className = `panel-body${["bom", "suppliers", "relations"].includes(tab) ? " doc" : ""}`;
    body.style.animation = "none";
    void body.offsetWidth;  // restart the fade, so switching tabs reads as a change of view
    body.style.animation = "";
    this.viewer = null;
    if (tab === "sheet") this.renderSheet(body);
    if (tab === "model") this.renderModel(body);
    if (tab === "bom") this.renderBom(body);
    if (tab === "suppliers") this.renderSuppliers(body);
    if (tab === "relations") this.renderRelations(body);
  }

  renderHead() {
    const { part } = this.state;
    const drawing = part.drawing;
    const rows = (part.bom || []).map((r) => r.row);
    const link = part.bom_link?.status;
    const facts = drawing
      ? [drawing.subsystem, drawing.scan ? "Scanned sheet" : "Clean sheet",
         rows.length ? `BOM row${rows.length > 1 ? "s" : ""} ${rows.join(", ")}` : "No BOM row"]
      : [`BOM row ${rows[0]}`, "No supplied drawing"];
    const available = { sheet: Boolean(drawing), model: Boolean(part.model_3d), bom: rows.length > 0, suppliers: rows.length > 0, relations: true };
    this.root.dataset.showing = part.ref;
    mount(this.root, html`
      <div class="panel-head">
        <div style="min-width:0">
          <div class="part-title"><span class="id">${part.ref}</span><h2>${part.name}</h2></div>
          <div class="part-facts">${facts.join(" · ")}${link && link !== "linked" ? html` · <span class="warn">${link} link</span>` : ""}</div>
        </div>
        <div class="tabs">${TABS.map(([key, label, glyph]) => html`<button type="button" data-tab="${key}" ${available[key] ? "" : raw("disabled")}>${
          glyph && key === "model" ? raw(icon(glyph, 14)) : ""}${label}</button>`)}<span class="tab-indicator"></span></div>
        <button type="button" class="icon-button panel-close" data-close aria-label="Close">${raw(icon("close"))}</button>
      </div>
      <div class="panel-body"></div>`);
  }

  renderSheet(body) {
    const { part, sheet, focus } = this.state;
    const drawing = part.drawing;
    const page = drawing.sheets[sheet - 1];
    const meta = this.drawings?.[part.ref]?.sheets[sheet - 1];
    const issues = part.attention || [];
    const serious = issues.filter((a) => a.cites.length);

    mount(body, html`
      <div class="stage"><div class="viewer"></div></div>
      <aside class="inspector">
        ${issues.length ? html`<section class="group">
          <h3 class="group-title">${serious.length ? "Needs review" : "Notes"}${serious.length ? html`<span class="count">${serious.length}</span>` : ""}</h3>
          <div class="rows">${issues.map((a) => html`<div class="issue">${raw(mark(a.cites.length ? "warn" : "info"))}
            <span>${a.text}${a.cites.length ? html`<span class="cites">${raw(a.cites.map((c) => chip(c)).join(""))}</span>` : ""}</span></div>`)}</div>
        </section>` : ""}
        <section class="group">
          <h3 class="group-title">Title block${drawing.sheets.length > 1 ? html`<select data-sheet aria-label="Sheet">${drawing.sheets.map((_, i) =>
            html`<option value="${i + 1}" ${i + 1 === sheet ? raw("selected") : ""}>Sheet ${i + 1} of ${drawing.sheets.length}</option>`)}</select>` : ""}</h3>
          <div class="rows">${Object.entries(page.title_block).map(([field, f]) => titleRow(field, f, focus))}</div>
        </section>
        ${page.callouts.length ? html`<section class="group">
          <h3 class="group-title">Callouts <span class="muted" style="font-weight:400">${page.callouts.length}</span></h3>
          <div class="rows">${page.callouts.map((c) => calloutRow(c, focus))}</div>
        </section>` : ""}
        ${part.bom?.length ? html`<section class="group">
          <h3 class="group-title">Bill of materials</h3>
          ${part.bom.map((row) => html`<button type="button" class="link-row" data-tab="bom"><span>Row ${row.row} · ${row.cells.name?.value || ""}</span>
            <span>${part.bom_link?.status || ""}${raw(icon("chevron", 14))}</span></button>`)}
        </section>` : ""}
      </aside>`);

    this.viewer = new SheetViewer($(".viewer", body), {
      onMark: (cite) => this.openCite(cite),
      onHover: (cite) => $$(".inspector [data-focus]", body).forEach((row) => row.classList.toggle("lit", Boolean(cite) && row.dataset.focus === cite)),
    });
    this.viewer.show({
      src: `/kb/${meta.image}`,
      width: meta.width,
      height: meta.height,
      marks: this.sheetMarks(),
      focus,
      badge: drawing.scan ? `${icon("scan", 14)}<span>Scanned sheet · marks are where OCR found the text</span>` : "",
    });
  }

  // The current sheet's marks, carrying the numbers the answer gave them.
  sheetMarks() {
    const { marks, sheet, refs } = this.state;
    return marks.filter((m) => (m.sheet || 1) === sheet).map((m) => ({ ...m, ...(refs.get(m.cite) || {}), red: m.red || refs.get(m.cite)?.red }));
  }

  // The sheet and the model side by side. Every dimension the model was built from is marked on
  // the sheet where it was read; pointing at either side, or at the list, lights up the other two.
  async renderModel(body) {
    const model = (await api.models())[this.state.part.ref];
    const meta = this.drawings?.[this.state.part.ref]?.sheets[0];
    mount(body, html`
      <div class="stage"><div class="linked"><div class="viewer"></div><div class="viewer model"></div></div></div>
      <aside class="inspector model-notes">${modelNotes(model)}</aside>`);

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
    const rows = $$(".dims-table [data-dim]", body);
    const light = (dims) => {
      sheet.highlight(new Set([...dims].map((i) => regionOf[i]).filter(Boolean)));
      viewer.highlight(dims);
      rows.forEach((r) => r.classList.toggle("lit", dims.has(Number(r.dataset.dim))));
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

    const [left, right] = $$(".linked .viewer", body);
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
    const { part, focus, refs } = this.state;
    mount(body, html`<div class="doc-inner">${part.bom.map((row) => html`
      <section class="group">
        <h3 class="group-title">Row ${row.row} · ${row.cells.name?.value || ""}</h3>
        ${part.bom_link ? html`<p class="note" style="margin:-2px 0 10px">${part.bom_link.status === "linked" ? "Linked" : `${capitalise(part.bom_link.status)} link`}: ${part.bom_link.basis} ${raw(chip(part.bom_link.cite, { label: "curation/links.csv", value: part.bom_link.status }))}
          ${part.drawing ? html`<button type="button" class="text-button" data-toggle="link-form">Change link</button>` : ""}</p>
          ${part.drawing ? html`<form class="inline-form" data-form="link-form" hidden onsubmit="return false">
            <label>BOM rows<input name="rows" value="${part.bom_link.rows.join(", ")}" inputmode="numeric"></label>
            <label>Certainty<select name="status">${["linked", "probable", "ambiguous"].map((s) => html`<option ${s === part.bom_link.status ? raw("selected") : ""}>${s}</option>`)}</select></label>
            <label class="grow">Reason<input name="reason" placeholder="What on the sheet and the BOM shows it"></label>
            <button type="button" class="button" data-file="link">File for review</button></form>` : ""}` : ""}
        <div class="rows">${Object.entries(BOM_COLUMNS).filter(([f]) => row.cells[f]).map(([f, column]) => {
          const cell = row.cells[f];
          return html`<div class="row${cell.cite === focus || refs.has(cell.cite) ? " hit" : ""}">
            <span class="k">${column}</span><span class="v">${cellText(f, cell)}${cell.corrected ? html`<small>Corrected, was ${cell.corrected.was}</small>` : ""}</span>
            <span>${raw(chip(cell.cite, { label: column, value: cell.value }))}</span></div>`;
        })}</div>
        ${row.drawings.length > 1 ? html`<p class="note" style="margin-top:8px">Also documented by ${row.drawings.filter((d) => d !== part.ref).join(", ")}.</p>` : ""}
      </section>`)}
      <p class="note">Supplier, price and order data are a BOM snapshot, not current availability.</p></div>`);
  }

  // Who supplied each row, and who else could: other sellers of a bought part from a dated web search,
  // or for a custom part what making it takes, checked against what each maker's own site states.
  async renderSuppliers(body) {
    const { part, focus, refs } = this.state;
    const data = await api.suppliers(part.ref);
    if (this.state.part !== part || this.state.tab !== "suppliers") return;
    const hit = (id) => (id === focus || refs.has(id) ? " hit" : "");
    mount(body, html`<div class="doc-inner">${data.parts.map((p) => html`<section class="group">
        <h3 class="group-title">Row ${p.ref.slice(4)} · ${p.name}<span class="muted" style="font-weight:400">${p.type}</span></h3>
        ${Object.keys(p.recorded).length ? html`<p class="label">Recorded in the BOM</p><div class="rows">${Object.entries(p.recorded).map(([f, c]) => html`
          <div class="row${hit(c.cite)}"><span class="k">${BOM_COLUMNS[f]}</span><span class="v">${f === "link" ? outbound(c.value, c.value) : c.value}</span>
          <span>${raw(chip(c.cite))}</span></div>`)}</div>` : ""}
        ${p.type === "Custom" ? made(p, hit) : p.identified_as ? bought(p, hit) : html`<p class="note">${p.not_searched}</p>`}
      </section>`)}
      <p class="note">${data.caveat}</p></div>`);
    $(".row.hit", body)?.scrollIntoView({ block: "center" });
  }

  renderRelations(body) {
    const groups = {};
    for (const r of this.state.part.relations || []) (groups[r.kind] ||= []).push(r);
    const add = html`<section class="group"><h3 class="group-title">Add a connection</h3>
      <form class="inline-form" onsubmit="return false">
        <label class="grow">Connects to<input name="other" list="part-refs" placeholder="A part or drawing"></label>
        <label>How<input name="relation" placeholder="is clamped by"></label>
        <label class="grow">Reason<input name="reason" placeholder="What shows it"></label>
        <button type="button" class="button" data-file="relation">File for review</button></form>
      <datalist id="part-refs"></datalist></section>`;
    if (!Object.keys(groups).length) {
      mount(body, html`<div class="doc-inner"><div class="empty-page"><strong>No recorded relations</strong>Neither the BOM, the system diagrams nor a matching fit connects this part to another.</div>${add}</div>`);
      return this.fillRefs(body);
    }
    mount(body, html`<div class="doc-inner">
      <a class="link-row" href="/graph?focus=${encodeURIComponent(this.state.part.ref)}" data-link><span>${raw(icon("graph", 14))} See these connections in the graph</span><span>${raw(icon("chevron", 14))}</span></a>
      ${Object.entries(groups).map(([kind, items]) => html`
      <section class="group"><h3 class="group-title">${KIND_TITLES[kind]}</h3>
        <div class="rows">${items.map((r) => html`<div class="relation">
          <span>${r.relation} <a href="/part/${r.other}" data-part="${r.other}">${r.other_name}</a> <span class="mono muted">${r.other}</span></span>
          <span>${raw(r.cites.map((c) => chip(c)).join(" "))}</span>
          ${r.note && r.note !== "Label text." ? html`<span class="muted">${r.note}</span>` : ""}
          <button type="button" class="text-button" data-toggle="withdraw-${r.other}">Withdraw</button>
          <form class="inline-form" data-form="withdraw-${r.other}" hidden onsubmit="return false">
            <label class="grow">Why it is wrong<input name="reason" placeholder="What shows they don't connect"></label>
            <button type="button" class="button quiet" data-file="withdraw" data-other="${r.other}">File for review</button></form></div>`)}</div>
      </section>`)}${add}</div>`);
    this.fillRefs(body);
  }

  async fillRefs(body) {
    const [drawings, rows] = await Promise.all([api.drawings(), api.bom()]);
    $("#part-refs", body).innerHTML = [...drawings.map((d) => [d.ref, d.name]), ...rows.map((r) => [`BOM.${r.row}`, r.name])]
      .map(([ref, name]) => `<option value="${ref}">${escape(name)}</option>`).join("");
  }

  // A correction filed from here waits for review like one filed from the chat.
  async file(button) {
    const { part } = this.state;
    const form = button.closest("form");
    const field = (name) => form ? $(`[name=${name}]`, form)?.value.trim() || "" : "";
    let body;
    if (button.dataset.use) {
      body = { kind: "dispute", target: button.dataset.use, value: button.dataset.value,
               reason: `Read the sheet: the ${button.dataset.reader === "OCR" ? "OCR" : "vision model"} reading is the right one.` };
    } else if (button.dataset.file === "link") {
      body = { kind: "link", drawing: part.ref, rows: field("rows").split(/[\s,;]+/).filter(Boolean).map(Number), status: field("status"), reason: field("reason") };
    } else if (button.dataset.file === "relation") {
      body = { kind: "relation", a: part.ref, b: field("other"), relation: field("relation"), reason: field("reason") };
    } else {
      body = { kind: "relation", a: part.ref, b: button.dataset.other, remove: true, reason: field("reason") };
    }
    if (!body.reason) return $("[name=reason]", form)?.focus();
    button.disabled = true;
    try {
      const filed = await api.propose(body);
      notify(`${filed.id} filed. It changes nothing until it is accepted on the Review page.`);
      api.forget("part:");
      document.dispatchEvent(new Event("corrections-changed"));
      this.openPart(part.ref, { tab: this.state.tab, sheet: this.state.sheet });
    } catch (error) {
      notify(error.message, true);
      button.disabled = false;
    }
  }

  // --- events ------------------------------------------------------------------------------

  click(e) {
    const toggle = e.target.closest("[data-toggle]");
    if (toggle) {
      const form = $(`[data-form="${CSS.escape(toggle.dataset.toggle)}"]`, this.root);
      form.hidden = !form.hidden;
      return form.hidden || $("input", form)?.focus();
    }
    const filing = e.target.closest("[data-file], [data-use]");
    if (filing) return this.file(filing);
    const tab = e.target.closest("[data-tab]");
    if (tab && !tab.disabled) { this.state.tab = tab.dataset.tab; return this.render(); }
    const cite = e.target.closest("[data-cite]");
    if (cite && !cite.closest(".viewer")) return this.openCite(cite.dataset.cite);  // a viewer handles its own marks
    const row = e.target.closest("[data-focus]");
    if (row?.dataset.focus) return this.openCite(row.dataset.focus);
    const link = e.target.closest("[data-part]");
    if (link) { e.preventDefault(); return this.openPart(link.dataset.part); }
    if (e.target.closest("[data-close]")) this.root.classList.remove("open");
  }
}

// A bought part: what the search identified it as, and who else sells it or something equivalent.
function bought(p, hit) {
  const id = p.identified_as;
  return html`<p class="label" style="margin-top:14px">Found by a web search, ${id.retrieved}</p>
    <div class="rows">
      <div class="row${hit(id.cite)}"><span class="k">Identified as</span><span class="v">${id.value || "Not identified"}<small>${id.own_brand ? "The seller's own brand. " : ""}${id.description}</small></span>
        <span>${raw(chip(id.cite))}</span></div>
      ${p.suggested.map((s) => html`<div class="row${hit(s.cite)}"><span class="k match">${raw(mark(MATCH[s.match][0], 14))}${MATCH[s.match][1]}</span>
        <span class="v">${outbound(s.url, s.seller)}<small>${s.note}</small></span><span>${raw(chip(s.cite))}</span></div>`)}
      ${p.suggested.length ? "" : html`<div class="row wide"><span class="v muted">The search found no other seller it could put a page to.</span><span></span></div>`}
    </div>`;
}

// A custom part: what making it takes, makers whose own sites say they can, and who made similar parts before.
function made(p, hit) {
  const r = p.requirements;
  const need = [
    ["Material", capitalise(r.materials.join(", ")) || "Not recorded", r.material_cites[0]],
    ["Process", r.processes.map((x) => `${PROCESS[x.process]}, ${x.why}`).join("\n") || "Not assumed without a material", null],
    ["Size", r.size ? `${r.size.mm} mm\n${r.size.how}` : "Not known", r.size?.cite],
    ["Tolerance", r.tightest ? `${r.tightest.text}\nTightest band ${(r.tightest.band_um / 1000).toFixed(3)} mm, about ±${(r.tightest.band_um / 2000).toFixed(3)} mm` : "No toleranced dimension read", r.tightest?.cite],
    ["Quantity", r.quantity?.count ?? "Not recorded", r.quantity?.cite],
  ];
  return html`<p class="label" style="margin-top:14px">What making it takes</p>
    <div class="rows">${need.map(([k, v, cite]) => html`<div class="row${cite ? hit(cite) : ""}"><span class="k">${k}</span><span class="v">${v}</span>
      <span>${cite ? raw(chip(cite)) : ""}</span></div>`)}</div>
    <p class="label" style="margin-top:14px">Makers whose sites say they can${p.makers[0] ? `, found ${p.makers[0].retrieved}` : ""}</p>
    ${p.makers.length ? html`<div class="rows">${p.makers.map((m) => html`<div class="row${hit(m.cite)}"><span class="k">${m.city || "Denmark"}</span>
      <span class="v">${outbound(m.url, m.name)}${m.checks.map((c) => html`<small class="check">${raw(mark(CHECK[c.result], 12))}${c.requirement}: ${c.detail}</small>`)}</span>
      <span>${raw(chip(m.cite))}</span></div>`)}</div>`
      : html`<p class="note">${r.processes.length ? "No maker found states this process with a material and size that fit." : "With no material recorded, no process is assumed and no maker is matched."}</p>`}
    ${p.made_before_by.length ? html`<p class="label" style="margin-top:14px">Made before for this machine</p>
      <div class="rows">${p.made_before_by.slice(0, 3).map((b) => html`<div class="row"><span class="k">${b.supplier}</span>
        <span class="v">${b.rows.length} custom part${b.rows.length > 1 ? "s" : ""}${r.materials.length ? ` in ${r.materials.join(" or ")}` : ""}: rows ${b.rows.slice(0, 8).join(", ")}${b.rows.length > 8 ? "…" : ""}</span>
        <span>${raw(chip(b.cites[0]))}</span></div>`)}</div>` : ""}`;
}

const PROCESS = { milling: "CNC milling", turning: "CNC turning", sheet: "Sheet metal", welding: "Welding", waterjet: "Waterjet cutting", polymer: "Polymer printing" };

// A link that leaves the app says so, and opens beside it.
const outbound = (url, text) => html`<a class="outbound" href="${url.startsWith("http") ? url : `https://${url}`}" target="_blank" rel="noopener noreferrer">${text}${raw(icon("external", 12))}</a>`;

// One title-block field: what it says, and how sure the reading is. Text-layer values need no mark.
function titleRow(field, f, focus) {
  const by = (method) => f.readings?.find((r) => r.method === method);
  const states = {
    exact: [null, ""],
    confirmed: ["agree", "Both readers agree"],
    "single reader": ["single", `${f.readings?.find((r) => r.cite === f.cite)?.method === "ocr" ? "OCR" : "Vision model"} only`],
    disputed: ["warn", "The readers disagree"],
    corrected: ["agree", `Corrected by ${f.corrected?.by}, was “${f.corrected?.was}”`],
    blank: ["blank", "Blank on the sheet"],
  };
  const [glyph, note] = states[f.status] || ["blank", "Unreadable"];
  const cite = f.cite || f.readings?.[0]?.cite || "";
  if (f.status === "disputed") {
    // Settling a dispute is choosing one reading after looking at the sheet; it waits for review like any correction.
    const [ocr, vision] = [by("ocr"), by("vision")];
    const choice = (mine, other, name) => html`<span class="reading"><span class="val">${oneLine(mine?.value) || "—"}</span><i>${name}</i>${
      mine?.value && other ? html`<button type="button" class="use" data-use="${other.cite}" data-value="${oneLine(mine.value)}" data-reader="${name}" title="File this reading for review">Use</button>` : ""}</span>`;
    return html`<div class="row${cite === focus ? " lit" : ""}" data-focus="${cite}">
      <span class="k">${FIELD_LABELS[field]}</span><span class="v">${choice(ocr, vision, "OCR")}${choice(vision, ocr, "Vision")}</span>
      <span>${raw(mark("warn"))}</span></div>`;
  }
  const value = html`${f.value || html`<span class="muted">—</span>`}${f.placeholder ? html`<small>Template placeholder</small>` : ""}`;
  return html`<button type="button" class="row${cite && cite === focus ? " lit" : ""}" data-focus="${cite}">
    <span class="k">${FIELD_LABELS[field]}</span><span class="v">${value}${note && f.status !== "disputed" ? html`<small>${note}</small>` : ""}</span>
    <span>${glyph ? raw(mark(glyph)) : ""}</span></button>`;
}

function calloutRow(c, focus) {
  const reader = c.read_by === "pdf-text" ? "" : `${c.read_by === "ocr" ? "OCR" : "Vision"}${c.confirmed_by_ocr ? " and OCR" : ""}`;
  return html`<button type="button" class="row wide${c.cite === focus ? " lit" : ""}" data-focus="${c.cite}">
    <span class="v"><span class="mono">${c.text}</span>
      <span class="callout-kind">${c.fit && c.tolerance?.upper !== undefined ? html`${c.fit} ${raw(band(c.tolerance))}` : c.kind}${reader ? ` · ${reader}` : ""}${
        c.fit_check ? html` · <span class="status-text red">failed ISO 286 check</span>` : ""}${c.corrected ? html` · corrected by ${c.corrected.by}, was ${c.corrected.was}` : ""}</span></span>
    <span>${c.fit_check ? raw(mark("warn")) : ""}</span></button>`;
}

// A fit's tolerance zone against the nominal size, drawn as ISO 286 draws it: a hole's H zone sits on
// the zero line, a g shaft's below it with a gap, a j zone straddles it. A misread fit shows at a glance.
function band({ upper, lower }) {
  const reach = Math.max(Math.abs(upper), Math.abs(lower)) || 1;
  const y = (v) => 9 - (v / reach) * 7;
  const um = (v) => `${v > 0 ? "+" : ""}${Math.round(v * 1000)} µm`;
  return `<svg class="band" width="30" height="18" viewBox="0 0 30 18" role="img" aria-label="tolerance zone ${um(lower)} to ${um(upper)}">
    <title>${um(lower)} to ${um(upper)} from the nominal size</title>
    <rect x="9" y="${y(upper)}" width="12" height="${Math.max(y(lower) - y(upper), 1)}"/><line x1="1" x2="29" y1="9" y2="9"/></svg>`;
}

function cellText(field, cell) {
  if (field === "datasheet" && cell.parsed?.files) {
    return `${cell.parsed.files.join(", ")} (attachment link expired ${cell.parsed.url_expired_on.join(", ")})`;
  }
  return cell.value;
}

function notify(text, error = false) {
  document.querySelector(".toast")?.remove();
  const toast = Object.assign(document.createElement("div"), { className: `toast${error ? " error" : ""}`, textContent: text });
  document.body.append(toast);
  setTimeout(() => toast.remove(), 5200);
}

const oneLine = (s) => (s || "").replace(/\s*\n\s*/g, " ");
const capitalise = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function imageSize(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = reject;
    img.src = src;
  });
}
