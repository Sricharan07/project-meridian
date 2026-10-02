// The graph page: how parts, drawings, subsystems, materials and suppliers connect, with every line
// backed by the evidence that asserts it.
//
// Three views, each laid out the same way every time so nothing jitters or tangles:
//   machine   the subsystems around a circle, joined by how many of their parts interface
//   focus     one node in the middle, its neighbours in sectors by kind of connection
//   path      a chain of evidence from one node to another, read left to right

import { api } from "./api.js";
import { chip } from "./render.js";
import { icon } from "./icons.js";
import { html, raw, mount, escape, $, $$ } from "./dom.js";

const W = 1000, H = 680, C = { x: W / 2, y: H / 2 };
const MACHINE = ["Box", "Powder", "Recoater", "Optical", "Gas Flow", "Z-axis"];
const KIND = { part: "Part", drawing: "Drawing", family: "Subsystem", material: "Material", supplier: "Supplier" };
// Where each kind of neighbour sits around a focused node: centre angle and spread, in degrees from the right, clockwise.
const SECTORS = { interfaces: [0, 120], documents: [-90, 70], part_of: [-148, 34], made_of: [180, 44], supplied_by: [140, 34] };
const GROUPS = [["interfaces", "Interfaces"], ["documents", "Drawings and BOM rows"], ["part_of", "Subsystem"], ["made_of", "Material"], ["supplied_by", "Supplier"]];
const TWEEN_MS = 480;
const EDGES = { list: [] };  // the loaded graph's edges, for the layout helpers below

export async function renderGraph(root, { navigate, openPart, openCite }) {
  const data = await api.graph();
  const nodes = new Map(data.nodes.map((n) => [n.id, n]));
  const edges = data.edges;
  EDGES.list = edges;
  const params = new URLSearchParams(location.search);
  const state = { focus: params.get("focus"), to: params.get("to"), trail: [], positions: new Map() };

  mount(root, html`<div class="page graph-page"><div class="graph-layout">
    <div class="graph-stage">
      <div class="graph-head">
        <nav class="crumbs"></nav>
        <label class="graph-find">${raw(icon("search", 14))}<input list="graph-nodes" placeholder="Focus on a part, drawing, material or supplier" aria-label="Focus on"></label>
      </div>
      <svg class="graph" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Knowledge graph"></svg>
      <div class="graph-tip" hidden></div>
      <div class="legend">${raw(legend())}</div>
    </div>
    <aside class="graph-panel inspector"></aside>
    <datalist id="graph-nodes">${data.nodes.filter((n) => n.kind !== "part" || n.label).map((n) => html`<option value="${n.label}" label="${KIND[n.kind]} · ${n.id}">`)}</datalist>
  </div></div>`);

  const svg = $("svg.graph", root);
  const panel = $(".graph-panel", root);
  const tip = $(".graph-tip", root);

  // --- views -------------------------------------------------------------------------------

  async function show({ focus = state.focus, to = state.to, push = true } = {}) {
    Object.assign(state, { focus, to });
    if (push) history.replaceState({}, "", `/graph${focus ? `?focus=${encodeURIComponent(focus)}${to ? `&to=${encodeURIComponent(to)}` : ""}` : ""}`);
    if (focus && to) return drawPath(await api.path(focus, to));
    if (focus && nodes.has(focus)) return drawFocus(focus);
    drawMachine();
  }

  function drawMachine() {
    const families = [...nodes.values()].filter((n) => n.kind === "family");
    const home = new Map(edges.filter((e) => e.kind === "part_of").map((e) => [e.a, e.b]));
    const size = (fid) => edges.filter((e) => e.kind === "part_of" && e.b === fid).length;
    const at = new Map();
    const inner = families.filter((f) => MACHINE.includes(f.label)).sort((a, b) => MACHINE.indexOf(a.label) - MACHINE.indexOf(b.label));
    const outer = families.filter((f) => !MACHINE.includes(f.label));
    const angle = new Map(inner.map((f, i) => [f.id, -90 + (360 / inner.length) * i]));
    inner.forEach((f) => at.set(f.id, polar(220, angle.get(f.id))));
    const links = new Map();
    for (const e of edges.filter((e) => e.kind === "interfaces")) {
      const [fa, fb] = [home.get(e.a), home.get(e.b)];
      if (!fa || !fb || fa === fb) continue;
      const key = [fa, fb].sort().join("|");
      links.set(key, [...(links.get(key) || []), e]);
    }
    // A family without drawings sits in the gap nearest the subsystem it connects to, so no line crosses the middle.
    const gaps = inner.map((_, i) => -60 + (360 / inner.length) * i);
    for (const f of outer.sort((a, b) => partners(b).length - partners(a).length)) {
      const want = partners(f).map((p) => angle.get(p)).find((a) => a !== undefined);
      const pick = gaps.sort((a, b) => (want === undefined ? 0 : distance(a, want) - distance(b, want)))[0];
      gaps.splice(gaps.indexOf(pick), 1);
      at.set(f.id, polar(320, pick));
    }
    function partners(f) {
      return [...links.keys()].filter((k) => k.split("|").includes(f.id)).map((k) => k.split("|").find((x) => x !== f.id));
    }
    const lines = [...links.entries()].map(([key, list]) => {
      const [a, b] = key.split("|");
      return { a, b, kind: "interfaces", weight: list.length, label: `${list.length} interface${list.length > 1 ? "s" : ""}`, cites: list.flatMap((e) => e.cites), source: "summary" };
    });
    paint({ at, lines, center: null, sizes: new Map(families.map((f) => [f.id, 14 + Math.sqrt(size(f.id)) * 3.2])), labels: "all",
            counts: new Map(families.map((f) => [f.id, size(f.id)])) });
    state.trail = [];
    crumbs();
    panelMachine(families, size, lines);
  }

  function drawFocus(id) {
    const node = nodes.get(id);
    const mine = edges.filter((e) => e.a === id || e.b === id);
    const other = (e) => (e.a === id ? e.b : e.a);
    const groups = new Map(GROUPS.map(([k]) => [k, []]));
    const seen = new Set();
    for (const e of mine) {
      const o = other(e);
      if (seen.has(`${e.kind}|${o}`)) continue;
      seen.add(`${e.kind}|${o}`);
      groups.get(e.kind)?.push({ id: o, edge: e });
    }
    const at = new Map([[id, { ...C }]]);
    const total = [...groups.values()].reduce((n, g) => n + g.length, 0);
    const [biggest, list] = [...groups.entries()].sort((a, b) => b[1].length - a[1].length)[0];
    // A subsystem, material or supplier has one big group (its parts): give it the whole circle.
    if (list.length > 12 && list.length / total > 0.7) {
      ring(beside(list.map((x) => x.id)), 0, 360, list.length > 16 ? [228, 300] : [265], at);
      for (const [k, g] of groups) if (k !== biggest) fan(g.map((x) => x.id), SECTORS[k] || [90, 40], [150], at);
    } else {
      for (const [k, g] of groups) fan(g.map((x) => x.id), SECTORS[k], g.length > 7 ? [205, 285] : [245], at);
    }
    const lines = [...groups.values()].flat().map((x) => x.edge);
    // Connections among the neighbours themselves, faintly: which of a subsystem's parts touch each other.
    const near = new Set(at.keys());
    for (const e of edges) if (e.kind === "interfaces" && e.a !== id && e.b !== id && near.has(e.a) && near.has(e.b)) lines.push({ ...e, faint: true });
    paint({ at, lines, center: id, labels: at.size > 30 ? "hover" : "all" });
    if (state.trail.at(-1) !== id) state.trail = [...state.trail.filter((t) => t !== id), id].slice(-5);
    crumbs();
    panelFocus(node, groups, total);
  }

  function drawPath(result) {
    if (result.error || !result.found) {
      drawFocus(state.focus);
      return panelNoPath(result);
    }
    const chain = [result.hops[0].from.ref, ...result.hops.map((h) => h.to.ref)];
    const at = new Map();
    const step = (W - 180) / Math.max(chain.length - 1, 1);
    chain.forEach((ref, i) => at.set(ref, { x: 90 + step * i, y: C.y + (chain.length > 5 ? (i % 2 ? 46 : -46) : 0) }));
    const lines = result.hops.map((h) => ({ a: h.from.ref, b: h.to.ref, kind: h.kind, label: h.relation, source: h.source, status: h.status, cites: h.cites, path: true }));
    paint({ at, lines, center: null, ends: [chain[0], chain.at(-1)], labels: "all", edgeLabels: true });
    crumbs();
    panelPath(result);
  }

  // --- drawing -----------------------------------------------------------------------------

  // Nodes glide from where they were to where they now belong; new ones grow out of the centre.
  function paint({ at, lines, center, sizes = new Map(), labels, ends = [], edgeLabels = false, counts = new Map() }) {
    const from = new Map([...at.keys()].map((id) => [id, state.positions.get(id) || (center ? { ...C } : at.get(id))]));
    const start = performance.now();
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const frame = (now) => {
      const t = reduced ? 1 : Math.min((now - start) / TWEEN_MS, 1);
      const k = 1 - (1 - t) ** 3;
      const pos = new Map([...at.entries()].map(([id, p]) => {
        const f = from.get(id);
        return [id, { x: f.x + (p.x - f.x) * k, y: f.y + (p.y - f.y) * k }];
      }));
      draw(pos, { lines, center, sizes, labels, ends, edgeLabels, counts, opacity: t });
      if (t < 1) requestAnimationFrame(frame);
      else state.positions = new Map(at);
    };
    requestAnimationFrame(frame);
  }

  function draw(pos, { lines, center, sizes, labels, ends, edgeLabels, counts, opacity }) {
    const edgeSvg = lines.filter((e) => pos.has(e.a) && pos.has(e.b)).map((e, i) => {
      const [p, q] = [pos.get(e.a), pos.get(e.b)];
      const cls = ["edge", e.kind, e.source, e.status, e.faint ? "faint" : "", e.path ? "on-path" : ""].filter(Boolean).join(" ");
      const width = e.weight ? 1.2 + Math.min(e.weight, 6) * 0.9 : "";
      const label = edgeLabels || e.weight
        ? `<text class="edge-label" x="${(p.x + q.x) / 2}" y="${(p.y + q.y) / 2 - 8}" text-anchor="middle">${escape(short(e.weight ? e.label : `${e.label}${e.source && e.source !== "summary" ? ` · ${e.source}` : ""}`, 34))}</text>` : "";
      return `<g class="${cls}" data-edge="${i}"><line x1="${p.x}" y1="${p.y}" x2="${q.x}" y2="${q.y}" ${width ? `style="stroke-width:${width}"` : ""}/><line class="hit" x1="${p.x}" y1="${p.y}" x2="${q.x}" y2="${q.y}"/>${label}</g>`;
    }).join("");
    const nodeSvg = [...pos.entries()].map(([id, p]) => {
      const n = nodes.get(id);
      const focus = id === center || ends.includes(id);
      const r = sizes.get(id) || (focus ? 13 : n.kind === "family" ? 11 : 7);
      const showLabel = labels === "all" || focus;
      const below = p.y >= C.y - 4 || !center;
      return `<g class="node ${n.kind}${focus ? " focus" : ""}" data-node="${escape(id)}" transform="translate(${p.x} ${p.y})" style="opacity:${id === center ? 1 : Math.max(opacity, 0.15)}">
        ${shape(n.kind, r)}${counts.has(id) ? `<text class="node-count" y="4" text-anchor="middle">${counts.get(id)}</text>` : ""}${showLabel ? `<text class="node-label" y="${below ? r + 15 : -r - 8}" text-anchor="middle">${escape(short(n.label, focus ? 34 : 24))}</text>` : ""}</g>`;
    }).join("");
    svg.innerHTML = `<g class="edges">${edgeSvg}</g><g class="nodes">${nodeSvg}</g>`;
    svg._lines = lines.filter((e) => pos.has(e.a) && pos.has(e.b));
  }

  // --- the panel beside the graph ----------------------------------------------------------

  function panelMachine(families, size, lines) {
    mount(panel, html`
      <section class="group"><h3 class="group-title">The machine</h3>
        <p class="note">Six subsystems carry the drawings; four more BOM families have parts but no drawings. A line means parts of the two
          subsystems interface, stated in the BOM or drawn on a system diagram; it is thicker the more of them there are.</p></section>
      <section class="group"><h3 class="group-title">Subsystems</h3><div class="rows families">${families
        .sort((a, b) => (MACHINE.indexOf(a.label) + 1 || 99) - (MACHINE.indexOf(b.label) + 1 || 99))
        .map((f) => html`<button type="button" class="row" data-focus-node="${f.id}"><span>${f.label}</span><span class="muted">${size(f.id)} items</span><span>${raw(icon("chevron", 14))}</span></button>`)}</div></section>
      <section class="group"><h3 class="group-title">Connections between subsystems</h3><div class="rows">${lines.length ? lines.sort((a, b) => b.weight - a.weight).map((l) => html`
        <div class="issue">${raw(icon("link", 14))}<span>${nodes.get(l.a).label} and ${nodes.get(l.b).label}: ${l.label} <span class="cites">${raw(l.cites.slice(0, 2).map((c) => chip(c)).join(""))}</span></span></div>`) : html`<div class="issue"><span class="muted">None recorded.</span></div>`}</div></section>`);
  }

  function panelFocus(node, groups, total) {
    const openable = node.kind === "part" || node.kind === "drawing";
    mount(panel, html`
      <section class="group">
        <p class="note" style="margin-bottom:2px">${node.kind === "family" && node.detail.startsWith("BOM family with") ? "BOM family" : KIND[node.kind]}${
          node.detail && !node.detail.startsWith("BOM family with") ? ` · ${node.detail}` : ""}</p>
        <h2 class="graph-title">${node.label}</h2>
        <div class="graph-actions">
          ${openable ? html`<button type="button" class="attach" data-open-part="${node.id}">${raw(icon("sheet", 14))}Open ${node.id}</button>` : ""}
        </div>
      </section>
      <section class="group"><h3 class="group-title">Connect to</h3>
        <label class="graph-find in-panel">${raw(icon("arrowRight", 14))}<input list="graph-nodes" data-connect placeholder="Another part or drawing" aria-label="Connect to"></label>
      </section>
      ${GROUPS.filter(([k]) => groups.get(k).length).map(([k, title]) => html`
        <section class="group"><h3 class="group-title">${title} <span class="muted" style="font-weight:400">${groups.get(k).length}</span></h3>
          <div class="rows">${groups.get(k).slice(0, 40).map(({ id, edge }) => html`<button type="button" class="row wide" data-focus-node="${id}">
            <span class="v">${nodes.get(id).label}<small>${edgeNote(edge)}</small></span><span>${raw(icon("chevron", 14))}</span></button>`)}</div>
          ${groups.get(k).length > 40 ? html`<p class="note" style="margin-top:6px">and ${groups.get(k).length - 40} more</p>` : ""}
        </section>`)}
      ${total ? "" : html`<p class="note">Nothing in the evidence connects this to anything else.</p>`}`);
  }

  function panelPath(result) {
    mount(panel, html`
      <section class="group">
        <p class="note" style="margin-bottom:2px">Connection</p>
        <h2 class="graph-title">${result.from.name} to ${result.to.name}</h2>
        <div class="graph-actions"><button type="button" class="attach" data-focus-node="${result.from.ref}">${raw(icon("arrowRight", 14))}Back to ${short(result.from.name, 22)}</button></div>
      </section>
      <section class="group"><h3 class="group-title">Steps <span class="muted" style="font-weight:400">${result.hops.length}</span></h3>
        <ol class="steps">${result.hops.map((h) => html`<li>
          <span>${h.from.name} <span class="muted">${stepWord(h)}</span> ${h.to.name}</span>
          <span class="cites">${raw(h.cites.slice(0, 3).map((c) => chip(c)).join(""))}</span></li>`)}</ol>
        ${result.note ? html`<p class="note">${result.note}</p>` : ""}
      </section>`);
  }

  function panelNoPath(result) {
    mount(panel, html`<section class="group"><h3 class="group-title">No connection</h3>
      <p class="note">${result.error || result.note}</p>
      <button type="button" class="attach" data-focus-node="${state.focus}">${raw(icon("arrowRight", 14))}Back</button></section>`);
  }

  function crumbs() {
    const nav = $(".crumbs", root);
    mount(nav, html`<button type="button" data-machine class="${state.focus ? "" : "current"}">Machine</button>${state.trail.map((id) => html`
      <span class="sep">${raw(icon("chevron", 12))}</span><button type="button" data-focus-node="${id}" class="${id === state.focus && !state.to ? "current" : ""}">${short(nodes.get(id)?.label || id, 26)}</button>`)}${
      state.to && nodes.get(state.to) ? html`<span class="sep">${raw(icon("chevron", 12))}</span><button type="button" class="current">to ${short(nodes.get(state.to).label, 22)}</button>` : ""}`);
  }

  // --- input -------------------------------------------------------------------------------

  root.onclick = (e) => {
    const n = e.target.closest("[data-node], [data-focus-node]");
    if (n) return show({ focus: n.dataset.node || n.dataset.focusNode, to: null });
    if (e.target.closest("[data-machine]")) return show({ focus: null, to: null });
    const open = e.target.closest("[data-open-part]");
    if (open) return openPart(open.dataset.openPart);
    const cite = e.target.closest("[data-cite]");
    if (cite) return openCite(cite.dataset.cite);
    const edge = e.target.closest("[data-edge]");
    if (edge) {
      const line = svg._lines[Number(edge.dataset.edge)];
      if (line?.cites?.length) openCite(line.cites[0]);
    }
  };
  root.addEventListener("change", (e) => {
    const input = e.target.closest("input[list=graph-nodes]");
    if (!input) return;
    const match = [...nodes.values()].find((n) => n.label === input.value || n.id === input.value);
    if (!match) return;
    input.value = "";
    if (input.matches("[data-connect]") && state.focus) show({ focus: state.focus, to: match.id });
    else show({ focus: match.id, to: null });
  });
  svg.addEventListener("pointerover", (e) => {
    const n = e.target.closest("[data-node]");
    const edge = e.target.closest("[data-edge]");
    if (n) {
      const node = nodes.get(n.dataset.node);
      tipAt(e, `<strong>${escape(node.label)}</strong><span>${KIND[node.kind]}${node.detail ? ` · ${escape(node.detail)}` : ""}</span>`);
      $$(`[data-edge]`, svg).forEach((g) => {
        const l = svg._lines[Number(g.dataset.edge)];
        g.classList.toggle("lit", l.a === node.id || l.b === node.id);
      });
    } else if (edge) {
      const l = svg._lines[Number(edge.dataset.edge)];
      edge.classList.add("lit");
      tipAt(e, `<strong>${escape(nodes.get(l.a).label)} – ${escape(nodes.get(l.b).label)}</strong><span>${escape(edgeNote(l))}</span><span class="muted">Click to see the evidence</span>`);
    }
  });
  svg.addEventListener("pointerout", (e) => {
    if (e.relatedTarget?.closest?.("[data-node], [data-edge]")) return;
    tip.hidden = true;
    $$(`[data-edge].lit`, svg).forEach((g) => g.classList.remove("lit"));
  });
  function tipAt(e, body) {
    const box = $(".graph-stage", root).getBoundingClientRect();
    tip.innerHTML = body;
    tip.hidden = false;
    tip.style.left = `${Math.min(e.clientX - box.left + 14, box.width - 260)}px`;
    tip.style.top = `${e.clientY - box.top + 14}px`;
  }

  show({ push: false });
}

// --- layout helpers ----------------------------------------------------------------------------

function polar(r, deg) {
  const a = (deg * Math.PI) / 180;
  return { x: C.x + r * Math.cos(a), y: C.y + r * Math.sin(a) };
}

// Spread ids across a sector; when there are many, alternate between radii so labels don't collide.
function fan(ids, [mid, spread], radii, at) {
  const n = ids.length;
  ids.forEach((id, i) => at.set(id, polar(radii[i % radii.length], n === 1 ? mid : mid - spread / 2 + (spread * i) / (n - 1))));
}

// Order a ring so each drawing sits next to the BOM row it documents.
function beside(ids) {
  const set = new Set(ids);
  const drawingsOf = new Map();
  for (const e of EDGES.list) if (e.kind === "documents" && set.has(e.a) && set.has(e.b)) drawingsOf.set(e.b, [...(drawingsOf.get(e.b) || []), e.a]);
  const placed = new Set();
  const out = [];
  for (const id of ids.filter((i) => !i.startsWith("D-")).sort((a, b) => Number(a.split(".")[1] || 0) - Number(b.split(".")[1] || 0))) {
    out.push(id);
    for (const d of drawingsOf.get(id) || []) if (!placed.has(d)) { out.push(d); placed.add(d); }
  }
  return [...out, ...ids.filter((i) => i.startsWith("D-") && !placed.has(i))];
}

const distance = (a, b) => Math.abs((((a - b) % 360) + 540) % 360 - 180);

function ring(ids, startDeg, spanDeg, radii, at) {
  ids.forEach((id, i) => at.set(id, polar(radii[i % radii.length], startDeg - 90 + (spanDeg * i) / ids.length)));
}

function shape(kind, r) {
  if (kind === "drawing") return `<rect x="${-r * 1.15}" y="${-r * 0.85}" width="${r * 2.3}" height="${r * 1.7}" rx="2"/>`;
  if (kind === "material") return `<rect x="${-r * 0.8}" y="${-r * 0.8}" width="${r * 1.6}" height="${r * 1.6}" transform="rotate(45)"/>`;
  if (kind === "supplier") return `<rect x="${-r * 0.85}" y="${-r * 0.85}" width="${r * 1.7}" height="${r * 1.7}" rx="${r * 0.35}"/>`;
  return `<circle r="${r}"/>`;
}

function edgeNote(e) {
  if (e.kind === "interfaces") return `${e.label} · ${{ stated: "stated in the BOM", diagram: "from a system diagram", inferred: "inferred from matching fits", reviewed: "added in review", summary: "between subsystems" }[e.source] || e.source}`;
  if (e.kind === "documents") return e.status === "linked" ? "documents this BOM row" : `${e.status} link`;
  if (e.kind === "made_of") return `${e.source === "sheet" ? "the sheet says" : "the BOM says"} “${short(e.label, 40)}”${e.status === "conflict" ? ", which conflicts with the other source" : ""}`;
  if (e.kind === "supplied_by") return e.label;
  return "belongs to";
}

function stepWord(h) {
  if (h.kind === "interfaces") return `interfaces with (${h.source})`;
  const sure = h.status && h.status !== "linked" ? ` (${h.status} link)` : "";
  if (h.kind === "documents") return `${h.from.kind === "drawing" ? "documents" : "is documented by"}${sure}`;
  return h.to.kind === "family" ? "belongs to" : "includes";
}

function legend() {
  const row = (cls, text) => `<span><svg width="28" height="8"><line class="edge ${cls}" x1="0" y1="4" x2="28" y2="4"/></svg>${text}</span>`;
  return [row("interfaces stated", "Stated in the BOM"), row("interfaces diagram", "From a diagram"), row("interfaces inferred", "Inferred from fits"),
    row("documents", "Drawing of a BOM row"), row("made_of conflict", "Sources disagree")].join("");
}

const short = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
