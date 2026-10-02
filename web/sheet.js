// A pan-and-zoom view of one sheet or diagram, with evidence regions drawn on top.
// The overlay uses the source's own coordinates (PDF points for sheets, pixels for diagrams), so a
// mark lands exactly where the extractor found the text. Numbered pins sit beside the marks in
// screen space, so they stay the same size at any zoom.

import { html, mount, raw, escape, $ } from "./dom.js";
import { citeLabel } from "./cite.js";
import { icon } from "./icons.js";

const GLIDE_MS = 460;

export class SheetViewer {
  constructor(root, { onMark, onHover, tools = "" } = {}) {
    this.root = root;
    this.onMark = onMark;
    this.onHover = onHover;
    this.scale = 1;
    this.x = 0;
    this.y = 0;
    this.pins = [];
    mount(root, html`
      <div class="canvas"><img alt=""><svg class="overlay" xmlns="http://www.w3.org/2000/svg"></svg></div>
      <div class="pins"></div>
      <div class="viewer-badge" hidden></div>
      <div class="capsule">
        ${raw(tools)}
        <button type="button" data-act="out" aria-label="Zoom out">${raw(icon("minus", 14))}</button>
        <span class="pct">100%</span>
        <button type="button" data-act="in" aria-label="Zoom in">${raw(icon("plus", 14))}</button>
        <span class="divider"></span>
        <button type="button" data-act="fit" aria-label="Fit the sheet">${raw(icon("fit", 14))}</button>
      </div>`);
    this.canvas = $(".canvas", root);
    this.img = $("img", root);
    this.svg = $("svg", root);
    this.layer = $(".pins", root);
    this.badge = $(".viewer-badge", root);
    this.pct = $(".pct", root);
    this.listen();
  }

  // `frame` is a box to fit instead of the whole sheet. Each mark may carry `n` (its reference number),
  // `red` (a disputed or failed reading) and `title`.
  show({ src, width, height, marks = [], focus = null, badge = "", frame = null }) {
    this.size = { width, height };
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    if (this.img.getAttribute("src") !== src) this.img.src = src;
    this.svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    this.setMarks(marks, focus);
    this.badge.hidden = !badge;
    this.badge.innerHTML = badge;

    const target = marks.find((m) => m.cite === focus);
    this.fit({ animate: false });
    // Open on the whole sheet, then travel to the evidence, so the reader sees where on the sheet it is.
    if (target) setTimeout(() => this.zoomTo(target.bbox), 140);
    else if (frame) this.frame(frame, { animate: false });
  }

  // Replace the marks without moving the view.
  setMarks(marks, focus = null) {
    this.svg.innerHTML = marks.map((m) => {
      const [x0, y0, x1, y1] = m.bbox;
      const pad = 2;
      const cls = `mark${m.red ? " red" : ""}${m.cite === focus ? " focus" : ""}`;
      return `<rect class="${cls}" data-cite="${escape(m.cite)}" x="${x0 - pad}" y="${y0 - pad}" width="${x1 - x0 + 2 * pad}" height="${y1 - y0 + 2 * pad}" rx="2"><title>${escape(m.title || citeLabel(m.cite))}</title></rect>`;
    }).join("");
    // One pin per numbered region, beside its top-left corner; regions with several numbers stack them.
    const byBox = new Map();
    for (const m of marks.filter((m) => m.n)) {
      const key = m.bbox.join();
      byBox.set(key, [...(byBox.get(key) || []), m]);
    }
    this.pins = [...byBox.values()].flatMap((group) => group.map((m, i) => ({ ...m, at: [m.bbox[0], m.bbox[1]], offset: i })));
    mount(this.layer, html`${this.pins.map((p, i) => html`<button type="button" class="pin${p.red ? " red" : ""}" data-cite="${p.cite}" style="animation-delay:${0.08 + i * 0.05}s">${p.n}</button>`)}`);
    if (this.size) this.apply();
  }

  highlight(keys) {
    for (const rect of this.svg.querySelectorAll("rect.mark")) rect.classList.toggle("lit", keys.has(rect.dataset.cite));
    for (const pin of this.layer.children) pin.classList.toggle("lit", keys.has(pin.dataset.cite));
  }

  has(cite) {
    return Boolean(this.svg.querySelector(`rect.mark[data-cite="${CSS.escape(cite)}"]`));
  }

  focus(cite) {
    const rect = this.svg.querySelector(`rect.mark[data-cite="${CSS.escape(cite)}"]`);
    if (!rect) return false;
    this.zoomTo([rect.x.baseVal.value, rect.y.baseVal.value, rect.x.baseVal.value + rect.width.baseVal.value, rect.y.baseVal.value + rect.height.baseVal.value]);
    return true;
  }

  // --- where the sheet sits ----------------------------------------------------------------

  fit({ animate = true } = {}) {
    const { clientWidth: w, clientHeight: h } = this.root;
    const scale = Math.min(w / this.size.width, h / this.size.height) * 0.94;
    this.go((w - this.size.width * scale) / 2, (h - this.size.height * scale) / 2, scale, animate);
  }

  frame([x0, y0, x1, y1], { margin = 24, animate = true } = {}) {
    const { clientWidth: w, clientHeight: h } = this.root;
    const scale = Math.min(w / (x1 - x0 + 2 * margin), h / (y1 - y0 + 2 * margin));
    this.go(w / 2 - ((x0 + x1) / 2) * scale, h / 2 - ((y0 + y1) / 2) * scale, scale, animate);
  }

  zoomTo([x0, y0, x1, y1]) {
    // Close enough to read the cited text, far enough to keep the view around it.
    const { clientWidth: w, clientHeight: h } = this.root;
    const fit = Math.min(w / this.size.width, h / this.size.height);
    const scale = Math.min(Math.max(fit, Math.min((w * 0.22) / (x1 - x0), (h * 0.14) / (y1 - y0))), fit * 3.5);
    this.go(w / 2 - ((x0 + x1) / 2) * scale, h / 2 - ((y0 + y1) / 2) * scale, scale, true);
  }

  zoomAt(factor, cx, cy, animate = false) {
    const next = Math.min(Math.max(this.scale * factor, 0.1), 12);
    this.go(cx - ((cx - this.x) * next) / this.scale, cy - ((cy - this.y) * next) / this.scale, next, animate);
  }

  go(x, y, scale, animate) {
    cancelAnimationFrame(this.gliding);
    if (!animate || matchMedia("(prefers-reduced-motion: reduce)").matches) {
      Object.assign(this, { x, y, scale });
      return this.apply();
    }
    // Ease in the log of the scale, so a big zoom feels as even as a small one.
    const from = { x: this.x, y: this.y, s: Math.log(this.scale) };
    const to = { x, y, s: Math.log(scale) };
    const start = performance.now();
    const step = (now) => {
      const t = Math.min((now - start) / GLIDE_MS, 1);
      const k = 1 - (1 - t) ** 4;
      this.scale = Math.exp(from.s + (to.s - from.s) * k);
      // Interpolate the point under the view's centre, not the corner, so the motion has no swing.
      const { clientWidth: w, clientHeight: h } = this.root;
      const c0 = { x: (w / 2 - from.x) / Math.exp(from.s), y: (h / 2 - from.y) / Math.exp(from.s) };
      const c1 = { x: (w / 2 - to.x) / Math.exp(to.s), y: (h / 2 - to.y) / Math.exp(to.s) };
      this.x = w / 2 - (c0.x + (c1.x - c0.x) * k) * this.scale;
      this.y = h / 2 - (c0.y + (c1.y - c0.y) * k) * this.scale;
      this.apply();
      if (t < 1) this.gliding = requestAnimationFrame(step);
    };
    this.gliding = requestAnimationFrame(step);
  }

  apply() {
    this.canvas.style.transform = `translate(${this.x}px, ${this.y}px) scale(${this.scale})`;
    // non-scaling-stroke ignores CSS transforms on ancestors, so the stroke is counter-scaled by hand.
    this.svg.style.setProperty("--unscale", String(1 / this.scale));
    this.pins.forEach((p, i) => {
      const el = this.layer.children[i];
      el.style.left = `${this.x + p.at[0] * this.scale - 12 - p.offset * 22}px`;
      el.style.top = `${this.y + p.at[1] * this.scale - 2}px`;
    });
    // Percent of the sheet's printed size: PDF points at 72 per inch, shown at 96 CSS pixels per inch.
    this.pct.textContent = `${Math.round(this.scale * 75)}%`;
  }

  // --- input -------------------------------------------------------------------------------

  listen() {
    this.root.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = this.root.getBoundingClientRect();
      this.zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });

    let drag = null;
    this.root.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".capsule, .pin, rect.mark")) return;
      cancelAnimationFrame(this.gliding);
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
    this.root.addEventListener("dblclick", (e) => { if (!e.target.closest(".capsule")) this.fit(); });

    this.root.addEventListener("click", (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      const { clientWidth: w, clientHeight: h } = this.root;
      if (act === "in") this.zoomAt(1.5, w / 2, h / 2, true);
      if (act === "out") this.zoomAt(1 / 1.5, w / 2, h / 2, true);
      if (act === "fit") this.fit();
      const mark = e.target.closest("rect.mark, .pin");
      if (mark && this.onMark) this.onMark(mark.dataset.cite);
    });

    if (!this.onHover) return;
    const over = (e) => {
      const mark = e.target.closest("rect.mark, .pin");
      if (mark) this.onHover(mark.dataset.cite);
    };
    const out = (e) => {
      if (e.target.closest("rect.mark, .pin") && !e.relatedTarget?.closest?.("rect.mark, .pin")) this.onHover(null);
    };
    for (const layer of [this.svg, this.layer]) {
      layer.addEventListener("pointerover", over);
      layer.addEventListener("pointerout", out);
    }
  }
}
