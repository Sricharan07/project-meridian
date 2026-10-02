// 3D reconstructions are built in the next step; until then the tab stays disabled
// because no part has a model_3d entry.

import { html, mount } from "./dom.js";

export class ModelViewer {
  constructor(root, notes) {
    this.root = root;
    this.notes = notes;
  }

  show() {
    mount(this.notes, html`<p class="muted">No reconstruction for this part.</p>`);
  }
}
