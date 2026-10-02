// Every supplied drawing, with how it was read and how sure the link to its BOM row is.

import { api } from "./api.js";
import { html, mount } from "./dom.js";

export async function renderParts(root, { open }) {
  const [drawings, status] = await Promise.all([api.drawings(), api.status()]);
  const scans = drawings.filter((d) => d.scan).length;
  mount(root, html`<div class="page"><div class="page-inner">
    <h2>Drawings</h2>
    <p class="lede">${drawings.length} sheets, ${scans} of them degraded scans, against ${status.bom_rows} BOM rows.
      The link column says how a sheet was matched to its BOM row; probable and ambiguous links are explained on the part.</p>
    <table class="facts">
      <tr><th>Drawing</th><th>Part</th><th>Subsystem</th><th>Sheet</th><th>BOM rows</th><th>Link</th><th>3D</th></tr>
      ${drawings.map((d) => html`<tr class="clickable" data-ref="${d.ref}">
        <td class="mono">${d.ref}</td><td>${d.name}</td><td>${d.subsystem}</td>
        <td>${d.scan ? "scan" : "clean"}${d.sheets.length > 1 ? ` · ${d.sheets.length} sheets` : ""}</td>
        <td class="mono">${d.bom_rows.join(", ")}</td>
        <td><span class="status ${d.link_status === "linked" ? "exact" : d.link_status === "probable" ? "single" : "disputed"}">${d.link_status}</span></td>
        <td>${d.model_3d ? "reconstruction" : ""}</td></tr>`)}
    </table></div></div>`);
  root.onclick = (e) => {
    const row = e.target.closest("tr[data-ref]");
    if (row) open(row.dataset.ref);
  };
}
