// Corrections proposed in chat, checked automatically, decided here by a person.
// Decided corrections stay listed: the history is part of the evidence.

import { api } from "./api.js";
import { chip } from "./render.js";
import { mark } from "./icons.js";
import { html, raw, mount, $ } from "./dom.js";

const RESULT = { pass: "agree", fail: "warn", note: "info" };
const CHANGE = { adds: "Adds", removes: "Removes", clears: "Clears the caveat", raises: "Raises a caveat" };
const NAME = "meridian.reviewer";

export async function renderReview(root, { openCite }) {
  const list = await fetch("/api/corrections").then((r) => r.json());
  const pending = list.filter((c) => c.status === "pending").length;
  mount(root, html`<div class="page"><div class="page-inner" style="max-width:1080px">
    <div class="page-head"><div><h1>Review</h1>
      <p>${list.length ? `${pending ? `${pending} waiting for a decision` : "Nothing waiting"}, ${list.length - pending} decided. ` : ""}Nothing changes until a correction is accepted, and accepting one keeps the original reading.</p></div></div>
    ${list.length ? list.map((c, i) => correction(c, i)) : html`<div class="empty-page"><strong>No corrections yet</strong>
      Tell the chat a value is wrong, and it files a correction here with the checks it ran.</div>`}
  </div></div>`);

  root.onclick = async (e) => {
    const cite = e.target.closest("[data-cite]");
    if (cite) return openCite(cite.dataset.cite);
    const button = e.target.closest("[data-decide]");
    if (!button) return;
    const form = button.closest("form");
    const by = $("[name=by]", form).value.trim();
    if (!by) return $("[name=by]", form).focus();
    try { localStorage.setItem(NAME, by); } catch { /* remembered name is a convenience only */ }
    button.disabled = true;
    const response = await fetch(`/api/corrections/${form.dataset.id}/decision`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accept: button.dataset.decide === "accept", by, note: $("[name=note]", form).value }),
    });
    if (!response.ok) { button.disabled = false; return alert((await response.json()).detail); }
    api.forget("part:");
    api.forget("evidence:");
    document.dispatchEvent(new Event("corrections-changed"));
    renderReview(root, { openCite });
  };
}

function correction(c, i) {
  const target = c.target_evidence;
  return html`<section class="correction" style="animation-delay:${i * 0.05}s">
    <header class="correction-head"><span class="id">${c.id}</span><h3>${c.part}</h3><span class="mono muted">${c.subject}</span>
      <span class="state ${c.status}">${c.status}</span><time>${when(c.proposed_at)}</time></header>
    <div class="correction-body">
      <div>
        <p class="label">${target?.label}, read by ${reader(target?.method)} ${raw(chip(c.target, target))}</p>
        <div class="diff">${raw(diff(c.current_value, c.proposed_value))}</div>
        <p class="label">Reason</p><p>${c.reason}</p>
        ${c.question ? html`<p class="label">Asked in chat</p><p class="muted">“${c.question}”</p>` : ""}
      </div>
      <div>
        <p class="label">Checks</p>
        <ul class="checklist">${c.checks.map((k) => html`<li>${raw(mark(RESULT[k.result]))}<span><strong>${k.name}.</strong> ${k.detail} ${raw(k.cites.map((id) => chip(id)).join(" "))}</span></li>`)}</ul>
        <p class="label">If accepted</p>
        ${c.impact.length
          ? html`<ul class="checklist">${c.impact.map((i) => html`<li>${raw(mark("info"))}<span><strong>${CHANGE[i.change]}:</strong> ${i.what}</span></li>`)}</ul>`
          : html`<p class="muted">No relation or caveat on this part changes; the corrected value replaces the current one in answers.</p>`}
      </div>
    </div>
    ${c.status === "pending" ? decisionForm(c) : html`<div class="decision">${raw(mark(c.status === "accepted" ? "agree" : "blank"))}
      ${c.status === "accepted" ? "Accepted" : "Rejected"} by ${c.decided_by}, ${when(c.decided_at)}${c.decision_note ? html`: ${c.decision_note}` : "."}</div>`}
  </section>`;
}

function decisionForm(c) {
  let remembered = "";
  try { remembered = localStorage.getItem(NAME) || ""; } catch { /* no storage, no prefill */ }
  return html`<form class="decide" data-id="${c.id}" onsubmit="return false">
    <label>Reviewer<input name="by" value="${remembered}" autocomplete="name" required></label>
    <label class="grow">Note<input name="note" placeholder="What you checked, such as reading the sheet at full size"></label>
    <button type="button" class="button quiet" data-decide="reject">Reject</button>
    <button type="button" class="button" data-decide="accept">Accept</button>
  </form>`;
}

// The two readings, with only what changed marked: "Ø262,0 H7 …" against "Ø262,0 j7 …".
function diff(was, now) {
  let start = 0;
  while (start < was.length && start < now.length && was[start] === now[start]) start++;
  let end = 0;
  while (end < was.length - start && end < now.length - start && was[was.length - 1 - end] === now[now.length - 1 - end]) end++;
  const esc = (s) => s.replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[ch]);
  const [head, tail] = [esc(was.slice(0, start)), esc(was.slice(was.length - end))];
  return `<span class="was">${head}<del>${esc(was.slice(start, was.length - end))}</del>${tail}</span>`
       + `<span>${head}<ins>${esc(now.slice(start, now.length - end))}</ins>${tail}</span>`;
}

const reader = (method) => ({ ocr: "OCR", vision: "the vision model", "pdf-text": "the text layer", csv: "the BOM export" })[method] || method;

function when(iso) {
  return iso ? new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "";
}
