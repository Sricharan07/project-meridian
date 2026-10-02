// Routes:  /            chat, with the evidence panel empty or on the last part
//          /part/D-026  chat, with the evidence panel on that part (shareable)
//          /drawings    every drawing
//          /review      corrections waiting for a decision

import { api } from "./api.js";
import { ChatView } from "./chat.js";
import { EvidencePanel } from "./evidence.js";
import { renderDrawings } from "./parts.js";
import { renderReview } from "./review.js";
import { setupJump } from "./jump.js";
import { icon } from "./icons.js";
import { $, $$, slide } from "./dom.js";

const layout = $("#layout");
const left = $("#left");

const evidence = new EvidencePanel($("#evidence"), { navigate });
const chat = new ChatView({ evidence });
setupJump({ open: (ref) => { navigate("/"); evidence.openPart(ref); } });

function navigate(path, { replace = false } = {}) {
  if (location.pathname === path) return;
  history[replace ? "replaceState" : "pushState"]({}, "", path);
  if (!replace) route();
}

async function route() {
  const path = location.pathname;
  const view = path.startsWith("/drawings") || path.startsWith("/parts") ? "drawings" : path.startsWith("/review") ? "review" : "chat";
  $$(".nav a").forEach((a) => a.classList.toggle("current", a.dataset.view === view));
  slide($(".nav-indicator"), $(".nav a.current"));
  layout.classList.toggle("wide", view !== "chat");

  if (view === "drawings") return renderDrawings(left, { open: (ref) => { navigate("/"); evidence.openPart(ref); } });
  if (view === "review") return renderReview(left, { openCite: (id) => { navigate("/"); evidence.openCite(id); } });

  if (!left.querySelector(".composer")) chat.mount(left);
  const part = path.match(/^\/part\/([\w.-]+)$/);
  const tab = { "3d": "model", bom: "bom", relations: "relations" }[new URLSearchParams(location.search).get("view")] || "sheet";
  if (part && evidence.state.part?.ref !== part[1]) evidence.openPart(part[1], { tab }).catch(() => evidence.empty());
  else if (!part && !evidence.state.part) evidence.empty();
}

async function countReviews() {
  const list = await fetch("/api/corrections").then((r) => r.json()).catch(() => []);
  const pending = list.filter((c) => c.status === "pending").length;
  const badge = $("#review-count");
  badge.hidden = !pending;
  badge.textContent = pending;
  slide($(".nav-indicator"), $(".nav a.current"));
}

function setupTheme() {
  const button = $("#theme");
  const paint = () => {
    const dark = document.documentElement.dataset.theme !== "light";
    button.innerHTML = icon(dark ? "sun" : "moon");
    button.setAttribute("aria-label", dark ? "Switch to light" : "Switch to dark");
  };
  button.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("meridian.theme", next); } catch { /* the choice just won't be remembered */ }
    paint();
    evidence.refresh();  // the 3D view reads its colours from the theme when it is drawn
  });
  paint();
}

document.addEventListener("click", (e) => {
  const link = e.target.closest("a[data-link]");
  if (!link || e.metaKey || e.ctrlKey) return;
  e.preventDefault();
  navigate(link.getAttribute("href"));
});
window.addEventListener("popstate", route);
window.addEventListener("resize", () => slide($(".nav-indicator"), $(".nav a.current")));
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && !["TEXTAREA", "INPUT"].includes(document.activeElement?.tagName)) {
    e.preventDefault();
    chat.focus();
  }
});
document.addEventListener("corrections-changed", countReviews);

$("#jump-open").insertAdjacentHTML("afterbegin", icon("search", 14));
setupTheme();
const drawings = await api.drawings();
evidence.drawings = Object.fromEntries(drawings.map((d) => [d.ref, d]));
await document.fonts?.ready;
route();
countReviews();
