// Corrections proposed in chat, checked automatically, decided here by a person.
// Decided corrections stay listed: the history is part of the evidence.

import { api } from "./api.js";
import { chip } from "./render.js";
import { mark } from "./icons.js";
import { html, raw, mount, $ } from "./dom.js";

const RESULT = { pass: "agree", fail: "warn", note: "info" };
const CHANGE = { adds: "Adds", removes: "Removes", clears: "Clears the caveat", raises: "Raises a caveat" };
const NAME = "meridian.reviewer";
const KINDS = { value: "Value", dispute: "Settles a dispute", link: "BOM link", relation: "Connection", drawing: "New drawing" };

export async function renderReview(root, { openCite }) {
  const [list, learning] = await Promise.all([fetch("/api/corrections").then((r) => r.json()), api.learning()]);
  const pending = list.filter((c) => c.status === "pending").length;
  const changed = new Map(learning.steps.map((s) => [s.id, s.changes]));
  mount(root, html`<div class="page"><div class="page-inner" style="max-width:1080px">
    <div class="page-head"><div><h1>Review</h1>
      <p>${list.length ? `${pending ? `${pending} waiting for a decision` : "Nothing waiting"}, ${list.length - pending} decided. ` : ""}Nothing changes until a correction is accepted, and accepting one keeps the original reading.</p></div></div>
    ${learning.steps.length ? progress(learning) : ""}
    ${list.length ? list.map((c, i) => correction(c, i, changed.get(c.id))) : html`<div class="empty-page"><strong>No corrections yet</strong>
      Tell the chat a value is wrong, and it files a correction here with the checks it ran.</div>`}
  </div></div>`);

  root.onclick = async (e) => {
    const cite = e.target.closest("[data-cite]");
    if (cite) return openCite(cite.dataset.cite);
    const pick = e.target.closest("[data-pick]");
    if (pick) return ($("[name=rows]", pick.closest("form")).value = pick.dataset.pick);
    const button = e.target.closest("[data-decide]");
    if (!button) return;
    const form = button.closest("form");
    const by = $("[name=by]", form).value.trim();
    if (!by) return $("[name=by]", form).focus();
    try { localStorage.setItem(NAME, by); } catch { /* remembered name is a convenience only */ }
    button.disabled = true;
    const response = await fetch(`/api/corrections/${form.dataset.id}/decision`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accept: button.dataset.decide === "accept", by, note: $("[name=note]", form).value,
        link: $("[name=rows]", form) ? { rows: $("[name=rows]", form).value.split(/[\s,;]+/).filter(Boolean).map(Number), status: $("[name=status]", form).value } : null }),
    });
    if (!response.ok) { button.disabled = false; return alert((await response.json()).detail); }
    api.forget("part:");
    api.forget("evidence:");
    api.forget("drawings");
    api.forget("bom");
    document.dispatchEvent(new Event("corrections-changed"));
    renderReview(root, { openCite });
  };
}

// What review has changed so far: each measure before any correction was accepted, and now.
function progress({ measures, before, now, steps }) {
  return html`<section class="group quality">
    <h3 class="group-title">What review has changed <span class="muted" style="font-weight:400">${steps.length} accepted</span></h3>
    <div class="rows">
      <div class="row head"><span>Measure</span><span>Before review</span><span>Now</span></div>
      ${measures.map(({ key, label }) => {
        const [was, is] = [before[key], now[key]];
        const of = key === "scan_right" ? ` of ${now.scan_total}` : "";
        return html`<div class="row${was !== is ? " moved" : ""}"><span>${label}</span><span class="mono">${was}${of}</span>
          <span class="mono">${is}${of}${was !== is ? html` <i>${is > was ? "+" : ""}${is - was}</i>` : ""}</span></div>`;
      })}
    </div>
    <p class="note" style="margin-top:8px">Each accepted correction is replayed in the order it was decided. The truth set and the reviewer read the same sheets, so this shows what each change moved, not an independent accuracy figure.</p>
  </section>`;
}

function correction(c, i, changes) {
  const target = c.target_evidence;
  const label = c.kind === "relation" ? (c.payload.remove ? "Withdraws a connection" : "Adds a connection") : KINDS[c.kind] || "Value";
  return html`<section class="correction" style="animation-delay:${i * 0.05}s">
    <header class="correction-head"><span class="id">${c.id}</span><span class="kind">${label}</span><h3>${c.part}</h3><span class="mono muted">${c.subject}</span>
      <span class="state ${c.status}">${c.status}</span><time>${when(c.proposed_at)}</time></header>
    <div class="correction-body">
      <div>
        ${c.kind === "drawing" ? html`<img class="added-sheet" src="/kb/${c.payload.image}" alt="First sheet of ${c.subject}">` : ""}
        <p class="label">${c.kind === "relation" ? `Between ${c.payload.a} and ${c.payload.b}` : c.kind === "link" ? `The link from ${c.subject} to the BOM`
          : c.kind === "drawing" ? `${c.payload.filename}, added to ${c.payload.subsystem}`
          : html`${target?.label}, read by ${reader(target?.method)} ${raw(chip(c.target, target))}`}</p>
        ${c.kind === "drawing" ? html`<p class="summary">${c.proposed_value}</p>` : html`<div class="diff">${raw(diff(c.current_value, c.proposed_value))}</div>`}
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
      ${c.status === "accepted" ? "Accepted" : "Rejected"} by ${c.decided_by}, ${when(c.decided_at)}${c.decision_note ? html`: ${c.decision_note}` : "."}
      ${changes?.length ? html`<span class="changed">Changed: ${changes.map((m, j) => html`${j ? " · " : ""}${m.label.toLowerCase()} ${m.before} → ${m.after}`)}</span>` : ""}</div>`}
  </section>`;
}

function decisionForm(c) {
  let remembered = "";
  try { remembered = localStorage.getItem(NAME) || ""; } catch { /* no storage, no prefill */ }
  const best = c.payload.candidates?.[0];
  return html`<form class="decide" data-id="${c.id}" onsubmit="return false">
    ${c.kind === "drawing" ? html`<div class="link-choice">
      <label>Documents BOM rows<input name="rows" value="${best ? best.row : ""}" inputmode="numeric" placeholder="51"></label>
      <label>Certainty<select name="status"><option>linked</option><option ${best && best.score < 3 ? raw("selected") : ""}>probable</option><option>ambiguous</option></select></label>
      ${c.payload.candidates?.length ? html`<span class="picks">Linker suggests ${c.payload.candidates.map((k) => html`<button type="button" class="text-button" data-pick="${k.row}">row ${k.row} ${k.name}</button>`)}</span>` : ""}
    </div>` : ""}
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
