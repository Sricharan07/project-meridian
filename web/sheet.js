// A pan-and-zoom view of one sheet or diagram, with evidence regions drawn on top.
// The overlay uses the source's own coordinates (PDF points for sheets, pixels for
// diagrams), so a highlight lands exactly where the extractor found the text.

import { html, mount, escape, $ } from "./dom.js";
import { citeLabel } from "./cite.js";

export class SheetViewer {
  constructor(root, { onMark, onHover } = {}) {
    this.root = root;
    this.onMark = onMark;
    this.onHover = onHover;
    this.scale = 1;
    this.x = 0;
    this.y = 0;
    mount(root, html`
      <div class="canvas"><img alt=""><svg xmlns="http://www.w3.org/2000/svg"></svg></div>
      <div class="viewer-tools"><button type="button" data-act="out" title="Zoom out">−</button><button type="button" data-act="in" title="Zoom in">+</button><button type="button" data-act="fit">Fit</button></div>
      <div class="viewer-caption" hidden></div>`);
    this.canvas = $(".canvas", root);
    this.img = $("img", root);
    this.svg = $("svg", root);
    this.caption = $(".viewer-caption", root);
    this.listen();
  }

  // `frame` is a box to fit in view instead of the whole sheet; a mark's `title` overrides its cite label.
  show({ src, width, height, marks = [], focus = null, caption = "", frame = null }) {
    this.size = { width, height };
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    if (this.img.getAttribute("src") !== src) this.img.src = src;
    this.svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    this.svg.innerHTML = marks.map((m) => {
      const [x0, y0, x1, y1] = m.bbox;
      const pad = 2;
      return `<rect class="mark${m.cite === focus ? " focus" : ""}" data-cite="${escape(m.cite)}" x="${x0 - pad}" y="${y0 - pad}" width="${x1 - x0 + 2 * pad}" height="${y1 - y0 + 2 * pad}" rx="2"><title>${escape(m.title || citeLabel(m.cite))}</title></rect>`;
    }).join("");
    this.caption.hidden = !caption;
    this.caption.textContent = caption;
    const target = marks.find((m) => m.cite === focus);
    requestAnimationFrame(() => (target ? this.zoomTo(target.bbox) : frame ? this.frame(frame) : this.fit()));
  }

  highlight(keys) {
    for (const rect of this.svg.querySelectorAll("rect.mark")) rect.classList.toggle("lit", keys.has(rect.dataset.cite));
  }

  fit() {
    const { clientWidth: w, clientHeight: h } = this.root;
    this.scale = Math.min(w / this.size.width, h / this.size.height) * 0.97;
    this.x = (w - this.size.width * this.scale) / 2;
    this.y = (h - this.size.height * this.scale) / 2;
    this.apply();
  }

  frame([x0, y0, x1, y1], margin = 24) {
    const { clientWidth: w, clientHeight: h } = this.root;
    this.scale = Math.min(w / (x1 - x0 + 2 * margin), h / (y1 - y0 + 2 * margin));
    this.x = w / 2 - ((x0 + x1) / 2) * this.scale;
    this.y = h / 2 - ((y0 + y1) / 2) * this.scale;
    this.apply();
  }

  zoomTo([x0, y0, x1, y1]) {
    // Close enough to read the cited text, far enough to keep the view around it.
    const { clientWidth: w, clientHeight: h } = this.root;
    const fit = Math.min(w / this.size.width, h / this.size.height);
    this.scale = Math.min(Math.max(fit, Math.min((w * 0.22) / (x1 - x0), (h * 0.14) / (y1 - y0))), fit * 3.5);
    this.x = w / 2 - ((x0 + x1) / 2) * this.scale;
    this.y = h / 2 - ((y0 + y1) / 2) * this.scale;
    this.apply();
  }

  zoomAt(factor, cx, cy) {
    const next = Math.min(Math.max(this.scale * factor, 0.1), 12);
    this.x = cx - ((cx - this.x) * next) / this.scale;
    this.y = cy - ((cy - this.y) * next) / this.scale;
    this.scale = next;
    this.apply();
  }

  apply() {
    this.canvas.style.transform = `translate(${this.x}px, ${this.y}px) scale(${this.scale})`;
    // non-scaling-stroke ignores CSS transforms on ancestors, so the stroke is counter-scaled by hand.
    this.svg.style.setProperty("--unscale", String(1 / this.scale));
  }

  listen() {
    this.root.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = this.root.getBoundingClientRect();
      this.zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });

    let drag = null;
    this.root.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".viewer-tools") || e.target.closest("rect.mark")) return;
      drag = { x: e.clientX - this.x, y: e.clientY - this.y };
      this.root.setPointerCapture(e.pointerId);
      this.root.classList.add("dragging");
    });
    this.root.addEventListener("pointermove", (e) => {
      if (!drag) return;
      this.x = e.clientX - drag.x;
      this.y = e.clientY - drag.y;
      this.apply();
    });
    const end = () => { drag = null; this.root.classList.remove("dragging"); };
    this.root.addEventListener("pointerup", end);
    this.root.addEventListener("pointercancel", end);
    this.root.addEventListener("dblclick", () => this.fit());

    this.root.addEventListener("click", (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      const { clientWidth: w, clientHeight: h } = this.root;
      if (act === "in") this.zoomAt(1.4, w / 2, h / 2);
      if (act === "out") this.zoomAt(1 / 1.4, w / 2, h / 2);
      if (act === "fit") this.fit();
      const mark = e.target.closest("rect.mark");
      if (mark && this.onMark) this.onMark(mark.dataset.cite);
    });

    if (!this.onHover) return;
    this.svg.addEventListener("pointerover", (e) => {
      const mark = e.target.closest("rect.mark");
      if (mark) this.onHover(mark.dataset.cite);
    });
    this.svg.addEventListener("pointerout", (e) => {
      if (e.target.closest("rect.mark") && !e.relatedTarget?.closest?.("rect.mark")) this.onHover(null);
    });
  }
}
