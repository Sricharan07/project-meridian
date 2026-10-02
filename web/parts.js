// Every supplied drawing, by subsystem: what the sheet looks like, how it was read, and how sure
// its link to a BOM row is.

import { api } from "./api.js";
import { icon } from "./icons.js";
import { html, raw, mount, $, $$ } from "./dom.js";

const ORDER = ["Box", "Powder", "Recoater", "Optical", "Gas Flow", "Z-axis"];
const FILTERS = { all: "All", scan: "Scans", model: "3D" };

export async function renderDrawings(root, { open }) {
  const [drawings, status] = await Promise.all([api.drawings(), api.status()]);
  const scans = drawings.filter((d) => d.scan).length;
  let filter = "all";

  mount(root, html`<div class="page"><div class="page-inner">
    <div class="page-head">
      <div><h1>Drawings</h1>
        <p>${drawings.length} sheets across six subsystems, ${scans} of them degraded scans, linked to ${status.bom_rows} BOM rows.</p></div>
      <div class="filters">${Object.entries(FILTERS).map(([key, label]) => html`<button type="button" data-filter="${key}">${label}</button>`)}<span class="filter-indicator"></span></div>
    </div>
    <div class="sections"></div>
  </div></div>`);

  const draw = () => {
    $$(".filters button", root).forEach((b) => b.classList.toggle("current", b.dataset.filter === filter));
    const current = $(".filters .current", root);
    const indicator = $(".filter-indicator", root);
    indicator.style.width = `${current.offsetWidth}px`;
    indicator.style.transform = `translateX(${current.offsetLeft - 3}px)`;
    const shown = drawings.filter((d) => filter === "all" || (filter === "scan" ? d.scan : d.model_3d));
    mount($(".sections", root), html`${ORDER.map((subsystem) => {
      const group = shown.filter((d) => d.subsystem === subsystem);
      return group.length ? html`<section class="subsystem"><h2>${subsystem}<span>${group.length}</span></h2>
        <div class="grid">${group.map((d, i) => card(d, i))}</div></section>` : "";
    })}`);
  };
  draw();

  root.onclick = (e) => {
    const button = e.target.closest("[data-filter]");
    if (button) { filter = button.dataset.filter; return draw(); }
    const item = e.target.closest("[data-ref]");
    if (item) open(item.dataset.ref);
  };
}

function card(d, i) {
  const link = d.link_status === "linked" ? "" : html`<span class="${d.link_status === "ambiguous" ? "red" : "accent"}">${d.link_status} link</span>`;
  return html`<button type="button" class="card" data-ref="${d.ref}" style="animation-delay:${Math.min(i * 0.03, 0.3)}s">
    <div class="thumb"><img src="/kb/${d.sheets[0].image}" alt="" loading="lazy"></div>
    <div class="meta"><div class="id">${d.ref}</div><div class="name">${d.name}</div>
      <div class="tags">
        <span>${raw(icon(d.scan ? "scan" : "sheet", 13))}${d.scan ? "Scan" : "Clean"}${d.sheets.length > 1 ? ` · ${d.sheets.length} sheets` : ""}</span>
        ${d.model_3d ? html`<span>${raw(icon("cube", 13))}3D</span>` : ""}
        ${link}
      </div></div>
  </button>`;
}
