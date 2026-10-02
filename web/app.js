// Routes:  /            chat, evidence panel empty or on the last part
//          /part/D-026  chat, evidence panel on that part (shareable)
//          /parts       every drawing
//          /review      corrections waiting for a decision

import { api } from "./api.js";
import { ChatView } from "./chat.js";
import { EvidencePanel } from "./evidence.js";
import { renderParts } from "./parts.js";
import { renderReview } from "./review.js";
import { $, $$ } from "./dom.js";

const layout = $("#layout");
const left = $("#left");

const evidence = new EvidencePanel($("#evidence"), { navigate });
const chat = new ChatView({ evidence });

function navigate(path, { replace = false } = {}) {
  if (location.pathname === path) return;
  history[replace ? "replaceState" : "pushState"]({}, "", path);
  if (!replace) route();
}

async function route() {
  const path = location.pathname;
  const view = path.startsWith("/parts") ? "parts" : path.startsWith("/review") ? "review" : "chat";
  $$(".bar nav a").forEach((a) => a.classList.toggle("current", a.dataset.view === view));
  layout.classList.toggle("wide", view !== "chat");

  if (view === "parts") return renderParts(left, { open: (ref) => { navigate("/"); evidence.openPart(ref); } });
  if (view === "review") return renderReview(left, { open: (ref) => { navigate("/"); evidence.openPart(ref); } });

  if (!left.querySelector(".composer")) chat.mount(left);
  const part = path.match(/^\/part\/([\w.-]+)$/);
  const tab = { "3d": "model", bom: "bom", relations: "relations" }[new URLSearchParams(location.search).get("view")] || "sheet";
  if (part && evidence.state.part?.ref !== part[1]) evidence.openPart(part[1], { tab }).catch(() => evidence.empty());
}

document.addEventListener("click", (e) => {
  const link = e.target.closest("a[data-link]");
  if (!link || e.metaKey || e.ctrlKey) return;
  e.preventDefault();
  navigate(link.getAttribute("href"));
});
window.addEventListener("popstate", route);
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement?.tagName !== "TEXTAREA" && document.activeElement?.tagName !== "INPUT") {
    e.preventDefault();
    chat.focus();
  }
});

const [status, drawings] = await Promise.all([api.status(), api.drawings()]);
evidence.drawings = Object.fromEntries(drawings.map((d) => [d.ref, d]));
$("#bar-meta").textContent = status.model
  ? `${status.model} · BOM snapshot ${status.snapshot.revision.slice(0, 7)}`
  : "No API key: chat shows evidence without written answers";
route();
