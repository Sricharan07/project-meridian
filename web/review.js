// Corrections proposed in chat, waiting for a person to accept or reject them.

import { html, mount } from "./dom.js";

export async function renderReview(root) {
  mount(root, html`<div class="page"><div class="page-inner">
    <h2>Review</h2>
    <p class="lede">Nothing is waiting for review.</p></div></div>`);
}
