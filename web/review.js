// Corrections proposed in chat, checked automatically, decided here by a person.
// Decided corrections stay listed: the history is part of the evidence.

import { api } from "./api.js";
import { chip } from "./render.js";
import { html, raw, mount, $ } from "./dom.js";

const RESULT = { pass: ["holds", "confirmed"], fail: ["fails", "conflict"], note: ["note", "exact"] };
const CHANGE = { adds: "Adds", removes: "Removes", clears: "Clears the caveat", raises: "Raises a caveat" };
const NAME = "meridian.reviewer";

export async function renderReview(root, { openCite }) {
  const list = await fetch("/api/corrections").then((r) => r.json());
  const pending = list.filter((c) => c.status === "pending").length;
  mount(root, html`<div class="page"><div class="page-inner">
    <h2>Review</h2>
    <p class="lede">${list.length
      ? `${pending} waiting for a decision, ${list.length - pending} decided.`
      : "Nothing has been proposed. Tell the chat that a value is wrong and it files a correction here."}
      Nothing changes until a correction is accepted, and accepting one keeps the original reading.</p>
    ${list.map((c) => correction(c))}
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
    renderReview(root, { openCite });
  };
}

function correction(c) {
  const target = c.target_evidence;
  return html`<section class="correction">
    <div class="correction-head"><span class="mono">${c.id}</span>
      <span class="status ${c.status === "pending" ? "single" : c.status === "accepted" ? "confirmed" : "exact"}">${c.status}</span>
      <span>${c.subject} ${c.part}</span><span class="muted">proposed ${when(c.proposed_at)}</span></div>
    <table class="facts">
      <tr><th>Corrects</th><td>${raw(chip(c.target, target))} <span class="muted">${target?.label}, read by ${target?.method}</span></td></tr>
      <tr><th>Reads now</th><td class="mono">${c.current_value}</td></tr>
      <tr><th>Proposed</th><td class="mono">${c.proposed_value}</td></tr>
      <tr><th>Reason</th><td>${c.reason}</td></tr>
      ${c.question ? html`<tr><th>Asked in chat</th><td class="muted">“${c.question}”</td></tr>` : ""}
    </table>
    <h3>Checks</h3>
    <ul class="checks">${c.checks.map((k) => html`<li><span class="status ${RESULT[k.result][1]}">${RESULT[k.result][0]}</span>
      <strong>${k.name}.</strong> ${k.detail} ${raw(k.cites.map((id) => chip(id)).join(""))}</li>`)}</ul>
    <h3>If accepted</h3>
    ${c.impact.length
      ? html`<ul class="checks">${c.impact.map((i) => html`<li><strong>${CHANGE[i.change]}:</strong> ${i.what}</li>`)}</ul>`
      : html`<p class="muted">No relation or caveat on this part changes; the corrected value replaces the current one in answers.</p>`}
    ${c.status === "pending" ? decisionForm(c) : html`<p class="decision">${c.status === "accepted" ? "Accepted" : "Rejected"} by ${c.decided_by} ${when(c.decided_at)}${c.decision_note ? html`: ${c.decision_note}` : "."}</p>`}
  </section>`;
}

function decisionForm(c) {
  let remembered = "";
  try { remembered = localStorage.getItem(NAME) || ""; } catch { /* no storage, no prefill */ }
  return html`<form class="decide" data-id="${c.id}" onsubmit="return false">
    <label>Reviewer<input name="by" value="${remembered}" autocomplete="name" required></label>
    <label class="grow">Note<input name="note" placeholder="What you checked, e.g. read the sheet at full size"></label>
    <button type="button" class="button" data-decide="accept">Accept</button>
    <button type="button" class="button quiet" data-decide="reject">Reject</button>
  </form>`;
}

function when(iso) {
  return iso ? new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "";
}
