// ⌘K / Ctrl K: open any drawing or BOM row by typing part of its id, name or subsystem.

import { api } from "./api.js";
import { html, mount, $ } from "./dom.js";

const MAC = /Mac|iPhone|iPad/.test(navigator.platform);
const LIMIT = 40;

export function setupJump({ open }) {
  const dialog = document.createElement("dialog");
  dialog.className = "jump";
  dialog.innerHTML = `<input type="text" placeholder="Drawing, part name, BOM row or subsystem" aria-label="Find a part"><ul role="listbox"></ul>`;
  document.body.append(dialog);
  const input = $("input", dialog);
  const list = $("ul", dialog);
  let items = [], shown = [], current = 0;

  const show = () => {
    const words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    shown = items.filter((i) => words.every((w) => i.text.includes(w))).slice(0, LIMIT);
    current = Math.min(current, Math.max(shown.length - 1, 0));
    mount(list, html`${shown.length ? shown.map((i, n) => html`
      <li role="option" data-n="${n}" aria-selected="${n === current}">
        <span class="mono">${i.id}</span><span>${i.name}</span><span class="muted">${i.detail}</span></li>`)
      : html`<li class="muted">Nothing matches.</li>`}`);
    list.querySelector("[aria-selected=true]")?.scrollIntoView({ block: "nearest" });
  };
  const choose = (n) => {
    const item = shown[n];
    if (!item) return;
    dialog.close();
    open(item.ref);
  };

  const start = async () => {
    if (!items.length) {
      const [drawings, rows] = await Promise.all([api.drawings(), api.bom()]);
      items = [
        ...drawings.map((d) => ({ ref: d.ref, id: d.ref, name: d.name,
          detail: [d.subsystem, d.scan ? "scan" : "", d.model_3d ? "3D" : ""].filter(Boolean).join(" · ") })),
        ...rows.map((r) => ({ ref: `BOM.${r.row}`, id: `row ${r.row}`, name: r.name,
          detail: [r.family, r.drawings.join(", ")].filter(Boolean).join(" · ") })),
      ].map((i) => ({ ...i, text: `${i.id} ${i.ref} ${i.name} ${i.detail}`.toLowerCase() }));
    }
    input.value = "";
    current = 0;
    show();
    dialog.showModal();
    input.focus();
  };

  input.addEventListener("input", () => { current = 0; show(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      current = (current + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % Math.max(shown.length, 1);
      show();
    }
    if (e.key === "Enter") { e.preventDefault(); choose(current); }
  });
  list.addEventListener("click", (e) => choose(Number(e.target.closest("[data-n]")?.dataset.n)));
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });  // the backdrop

  document.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() === "k" && (MAC ? e.metaKey : e.ctrlKey)) { e.preventDefault(); start(); }
  });
  const button = $("#jump-open");
  $("kbd", button).textContent = MAC ? "⌘K" : "Ctrl K";
  button.addEventListener("click", start);
}
