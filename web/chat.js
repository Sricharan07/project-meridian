// The conversation rail. Each answer arrives with numbered references, the sheets it rests on and a
// record of how it was produced; the first sheet opens beside it, already marked.

import { api } from "./api.js";
import { answer, ref, isRed, sourceLabel } from "./render.js";
import { icon } from "./icons.js";
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
];
const SHOWN_SOURCES = 4;
const STORE = "meridian.chat";

export class ChatView {
  constructor({ evidence, navigate }) {
    this.evidence = evidence;
    this.navigate = navigate;
    this.messages = load();
    this.busy = false;
    this.turns = new Map();  // index in messages -> the turn's references, for re-opening its evidence
  }

  mount(root) {
    this.root = root;
    mount(root, html`
      <div class="messages" aria-live="polite"></div>
      <div class="composer"><form>
        <textarea rows="1" placeholder="Ask about a part, a material or a cost" aria-label="Question"></textarea>
        <button class="send" type="submit" aria-label="Ask">${raw(icon("arrowUp"))}</button>
      </form></div>`);
    this.list = $(".messages", root);
    this.input = $("textarea", root);
    this.button = $(".send", root);
    $("form", root).addEventListener("submit", (e) => { e.preventDefault(); this.send(this.input.value); });
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this.send(this.input.value); }
    });
    this.input.addEventListener("input", () => {
      this.input.style.height = "auto";
      this.input.style.height = `${this.input.scrollHeight}px`;
      this.button.disabled = this.busy || !this.input.value.trim();
    });
    this.list.addEventListener("click", (e) => this.click(e));
    this.list.addEventListener("pointerover", (e) => this.hover(e, true));
    this.list.addEventListener("pointerout", (e) => this.hover(e, false));
    this.button.disabled = true;
    this.draw();
  }

  focus() { this.input?.focus(); }

  async send(text) {
    const question = text.trim();
    if (!question || this.busy) return;
    this.busy = true;
    this.input.value = "";
    this.input.style.height = "auto";
    this.button.disabled = true;
    const history = this.messages.filter((m) => !m.error).map((m) => ({ role: m.role, content: m.role === "user" ? m.text : m.turn.answer }));
    this.messages.push({ role: "user", text: question });
    this.draw({ pending: true });
    try {
      const turn = await api.ask(question, history);
      this.messages.push({ role: "assistant", turn });
      const { refs } = answer(turn.answer, turn.citations);
      const first = turn.attachments[0];
      if (first) this.evidence.openAttachment(first, refs);
      if (turn.steps.some((s) => s.tool === "propose_correction")) document.dispatchEvent(new Event("corrections-changed"));
    } catch (error) {
      this.messages.push({ role: "assistant", error: String(error.message || error) });
    }
    this.busy = false;
    save(this.messages);
    this.draw();
  }

  draw({ pending = false } = {}) {
    if (!this.messages.length && !pending) {
      mount(this.list, html`<div class="welcome">
        <h1>Ask about any part of the machine</h1>
        <p>Every answer points to the drawing region or BOM cell it comes from.</p>
        ${EXAMPLES.map((q) => html`<button type="button" class="suggestion" data-example="${q}"><span>${q}</span>${raw(icon("arrowRight", 14))}</button>`)}
      </div>`);
      return;
    }
    this.turns.clear();
    mount(this.list, html`${this.messages.map((m, i) => this.message(m, i))}
      ${pending ? html`<div class="thinking"><span class="spinner"></span>Reading the evidence…</div>` : ""}`);
    this.list.scrollTop = this.list.scrollHeight;
  }

  message(m, index) {
    if (m.role === "user") return html`<div class="ask"><span>${m.text}</span></div>`;
    if (m.error) return html`<div class="turn"><div class="warning">Couldn't answer: ${m.error}</div></div>`;
    const t = m.turn;
    const { html: body, refs } = answer(t.answer, t.citations);
    this.turns.set(index, refs);
    const known = refs.filter((r) => r.evidence);
    const drawings = t.attachments.filter((a) => a.type === "drawing");
    return html`<div class="turn" data-turn="${index}">
      <div class="answer">${raw(body)}</div>
      ${t.check.ok === false ? html`<div class="warning">${problems(t.check)}</div>` : ""}
      ${known.length ? html`<div class="sources">${known.map((r, i) => source(r, i >= SHOWN_SOURCES))}</div>
        ${known.length > SHOWN_SOURCES ? html`<button type="button" class="more" data-more>Show ${known.length - SHOWN_SOURCES} more</button>` : ""}` : ""}
      <div class="turn-foot">
        ${t.attachments.filter((a) => a.type === "graph").slice(0, 1).map((a) => html`<button type="button" class="attach" data-graph="${a.focus || ""}" data-to="${a.to || ""}">${raw(icon("graph", 14))}Graph</button>`)}
        ${drawings.map((a) => html`<button type="button" class="attach" data-open="${a.ref}">${raw(icon("sheet", 14))}<span class="mono">${a.ref}</span>${a.name}</button>
          ${a.model_3d ? html`<button type="button" class="attach" data-model="${a.ref}">${raw(icon("cube", 14))}3D</button>` : ""}`)}
        ${trace(t)}
      </div>
    </div>`;
  }

  click(e) {
    const example = e.target.closest("[data-example]");
    if (example) return this.send(example.dataset.example);
    const refs = this.turns.get(Number(e.target.closest("[data-turn]")?.dataset.turn));
    const more = e.target.closest("[data-more]");
    if (more) {
      more.parentElement.querySelectorAll(".source[hidden]").forEach((s) => (s.hidden = false));
      return more.remove();
    }
    const cite = e.target.closest("[data-cite]");
    if (cite) return this.evidence.openCite(cite.dataset.cite, refs);
    const graphButton = e.target.closest("[data-graph]");
    if (graphButton) {
      const { graph: focus, to } = graphButton.dataset;
      return this.navigate(`/graph${focus ? `?focus=${encodeURIComponent(focus)}${to ? `&to=${encodeURIComponent(to)}` : ""}` : ""}`);
    }
    const model = e.target.closest("[data-model]");
    if (model) return this.evidence.openPart(model.dataset.model, { tab: "model" });
    const open = e.target.closest("[data-open]");
    if (open) {
      const turn = this.messages[Number(open.closest("[data-turn]").dataset.turn)].turn;
      return this.evidence.openAttachment(turn.attachments.find((a) => a.ref === open.dataset.open), refs);
    }
  }

  // Pointing at a reference lights it everywhere it appears: in the answer, the source list and on the sheet.
  hover(e, entering) {
    const target = e.target.closest("[data-cite]");
    if (!target || (!entering && target.contains(e.relatedTarget))) return;
    const id = entering ? target.dataset.cite : null;
    const turn = target.closest("[data-turn]");
    turn?.querySelectorAll("[data-cite]").forEach((el) => el.classList.toggle("lit", el.dataset.cite === id));
    this.evidence.preview(id);
  }
}

function source(r, hidden) {
  const e = r.evidence;
  const value = String(e.value || "").split("\n")[0] || "blank";
  return html`<button type="button" class="source${isRed(e) ? " red" : ""}" data-cite="${r.id}" ${hidden ? raw("hidden") : ""}>
    ${raw(ref(r, { inline: false }))}<span class="where">${sourceLabel(r.id, e)}</span><span class="value">${value}</span></button>`;
}

function problems(check) {
  const parts = [];
  if (check.untraced_numbers.length) parts.push(`figures not found in the evidence: ${check.untraced_numbers.join(", ")}`);
  if (check.unknown_citations.length) parts.push(`citations that don't exist: ${check.unknown_citations.join(", ")}`);
  return `This answer failed its check${check.rewritten ? " even after a rewrite" : ""}, so treat it with care: ${parts.join("; ")}.`;
}

function trace(t) {
  if (t.model === "offline") return html`<details class="trace"><summary>No API key, so no model was called</summary></details>`;
  if (t.model === "recorded") return html`<details class="trace"><summary>${t.note}</summary></details>`;
  const lookups = t.steps.length === 1 ? "1 lookup" : `${t.steps.length} lookups`;
  return html`<details class="trace">
    <summary>${lookups} · ${t.seconds.toFixed(1)} s · $${t.usage.usd.toFixed(4)}${t.check.ok ? " · every figure traced" : ""}</summary>
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
