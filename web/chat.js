// The chat column. Each answer arrives with its citations, the sheets it rests on and
// a record of how it was produced; the first sheet opens beside it automatically.

import { api } from "./api.js";
import { answerHtml, chip } from "./render.js";
import { html, raw, mount, $ } from "./dom.js";

// Questions from eval/questions.json: without an API key the app replays their recorded answers.
const EXAMPLES = [
  "Is the recoater arm made of stainless steel?",
  "Show me the recoater mount block.",
  "How thick is the heating element plate?",
  "Which drawing documents the recoater stage plate?",
  "What connects to the print platform?",
  "What did the Box subsystem cost, and what is missing from that figure?",
  "What does the recoater arm weigh?",
  "What does D-030 weigh?",
];

const STORE = "meridian.chat";

export class ChatView {
  constructor({ evidence }) {
    this.evidence = evidence;
    this.messages = load();
    this.busy = false;
  }

  mount(root) {
    this.root = root;
    mount(root, html`
      <div class="messages" aria-live="polite"></div>
      <div class="composer"><form>
        <textarea rows="1" placeholder="Ask about a part, a subsystem, a material or a cost" aria-label="Question"></textarea>
        <button class="button" type="submit">Ask</button>
      </form></div>`);
    this.list = $(".messages", root);
    this.input = $("textarea", root);
    $("form", root).addEventListener("submit", (e) => { e.preventDefault(); this.send(this.input.value); });
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this.send(this.input.value); }
    });
    this.input.addEventListener("input", () => {
      this.input.style.height = "auto";
      this.input.style.height = `${this.input.scrollHeight}px`;
    });
    this.list.addEventListener("click", (e) => this.click(e));
    this.draw();
  }

  focus() { this.input?.focus(); }

  async send(text) {
    const question = text.trim();
    if (!question || this.busy) return;
    this.busy = true;
    this.input.value = "";
    this.input.style.height = "auto";
    const history = this.messages.filter((m) => !m.error).map((m) => ({ role: m.role, content: m.role === "user" ? m.text : m.turn.answer }));
    this.messages.push({ role: "user", text: question });
    this.draw({ pending: true });
    try {
      const turn = await api.ask(question, history);
      this.messages.push({ role: "assistant", turn });
      const first = turn.attachments[0];
      if (first) this.evidence.openAttachment(first, Object.keys(turn.citations));
    } catch (error) {
      this.messages.push({ role: "assistant", error: String(error.message || error) });
    }
    this.busy = false;
    save(this.messages);
    this.draw();
  }

  draw({ pending = false } = {}) {
    if (!this.messages.length && !pending) {
      mount(this.list, html`<div class="examples">
        <p>Answers cite the drawing region or BOM cell each fact comes from.</p>
        ${EXAMPLES.map((q) => html`<button type="button" data-example="${q}">${q}</button>`)}</div>`);
      return;
    }
    mount(this.list, html`${this.messages.map((m) => this.message(m))}
      ${pending ? html`<div class="message pending">Looking it up…</div>` : ""}`);
    this.list.scrollTop = this.list.scrollHeight;
    $(".composer button", this.root).disabled = pending;
  }

  message(m) {
    if (m.role === "user") return html`<div class="message user">${m.text}</div>`;
    if (m.error) return html`<div class="message"><div class="check">Could not answer: ${m.error}</div></div>`;
    const t = m.turn;
    const drawings = t.attachments.filter((a) => a.type === "drawing");
    return html`<div class="message">
      <div class="body">${raw(answerHtml(t.answer, t.citations))}</div>
      ${t.check.ok === false ? html`<div class="check">${problems(t.check)}</div>` : ""}
      ${drawings.length ? html`<div class="opened">Sheets: ${drawings.map((a, i) => html`${i ? ", " : ""}<button type="button" data-open="${a.ref}">${a.ref} ${a.name}</button>${
        a.model_3d ? html` (<button type="button" data-model="${a.ref}">3D reconstruction</button>)` : ""}`)}</div>` : ""}
      ${trace(t)}
    </div>`;
  }

  click(e) {
    const example = e.target.closest("[data-example]");
    if (example) return this.send(example.dataset.example);
    const more = e.target.closest("[data-more]");
    if (more) return more.outerHTML = more.dataset.more.split(",").map((id) => chip(id)).join("");
    const cite = e.target.closest("[data-cite]");
    if (cite) return this.evidence.openCite(cite.dataset.cite);
    const model = e.target.closest("[data-model]");
    if (model) return this.evidence.openPart(model.dataset.model, { tab: "model" });
    const open = e.target.closest("[data-open]");
    if (open) {
      const turn = this.messages.find((m) => m.turn?.attachments.some((a) => a.ref === open.dataset.open))?.turn;
      const attachment = turn?.attachments.find((a) => a.ref === open.dataset.open);
      return this.evidence.openAttachment(attachment, Object.keys(turn.citations));
    }
  }
}

function problems(check) {
  const parts = [];
  if (check.untraced_numbers.length) parts.push(`figures not found in the evidence: ${check.untraced_numbers.join(", ")}`);
  if (check.unknown_citations.length) parts.push(`citations that do not exist: ${check.unknown_citations.join(", ")}`);
  return `This answer failed its check${check.rewritten ? " even after a rewrite" : ""}. Treat it with care: ${parts.join("; ")}.`;
}

function trace(t) {
  if (t.model === "offline") return html`<details class="trace"><summary>No API key, so no model was called</summary></details>`;
  if (t.model === "recorded") return html`<details class="trace"><summary>${t.note}</summary></details>`;
  const lookups = t.steps.length === 1 ? "1 lookup" : `${t.steps.length} lookups`;
  return html`<details class="trace">
    <summary>How this was answered · ${lookups} · ${t.seconds.toFixed(1)} s · $${t.usage.usd.toFixed(4)}</summary>
    <ol>${t.steps.map((s) => html`<li><span class="mono">${s.tool}(${Object.values(s.arguments).filter((v) => v != null).map((v) => JSON.stringify(v)).join(", ")})</span> <span class="muted">${s.ms} ms</span></li>`)}</ol>
    <div>${t.check.ok ? "Every figure and citation was traced to the evidence." : "The check found problems, listed above."}${t.check.rewritten ? " The first draft failed the check and was rewritten." : ""}</div>
    <div class="muted">${t.model} · ${t.usage.input_tokens} tokens in, ${t.usage.output_tokens} out · ${t.usage.calls} model calls</div>
  </details>`;
}

function load() {
  try { return JSON.parse(sessionStorage.getItem(STORE)) || []; } catch { return []; }
}

function save(messages) {
  try { sessionStorage.setItem(STORE, JSON.stringify(messages.slice(-40))); } catch { /* storage unavailable: the chat still works, it just won't survive a reload */ }
}
