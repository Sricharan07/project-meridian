// An orbitable reconstruction, labelled as one, with its dimensions drawn on it the way the sheet
// gives them. Each dimension knows the callout it was read from, so the panel can point from the
// model to the sheet and back. A section plane cuts the part like the sheet's own section views.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { toCreasedNormals } from "three/addons/utils/BufferGeometryUtils.js";
import { html, raw, mount } from "./dom.js";
import { chip } from "./render.js";

const FINISH = { "EN AW-5005": 0xc4c8cc, "AISI 316": 0xa7aaad, "silicone rubber": 0xb8644a };
const HOW = { measured: "measured off the sheet", "as drawn": "as drawn, not dimensioned", limit: "chosen within a limit" };
const BACKGROUND = 0xeceae8;
const INK = { normal: 0x6b645e, lit: 0x0f766e };

export class ModelViewer {
  constructor(root, { onHover = () => {}, onPick = () => {} } = {}) {
    this.root = root;
    this.onHover = onHover;
    this.onPick = onPick;
    this.dims = [];
  }

  async show(model) {
    mount(this.root, html`
      <div class="dims"></div>
      <div class="viewer-tools">
        <label class="section-range" hidden><input type="range" step="0.1" aria-label="Section position"></label>
        <button type="button" data-act="section" aria-pressed="false">Section</button>
        <button type="button" data-act="dims" aria-pressed="true">Dimensions</button>
        <button type="button" data-act="fit">Fit</button>
      </div>
      <div class="viewer-caption model-label">Reconstruction from the 2D drawing, not native CAD.
        Mass ${fmt(model.mass.computed_g, 1)} g against ${fmt(model.mass.sheet_g, 1)} g on the sheet.</div>`);

    const renderer = new THREE.WebGLRenderer({ antialias: true, stencil: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setClearColor(BACKGROUND);
    renderer.localClippingEnabled = true;
    this.root.prepend(renderer.domElement);
    this.renderer = renderer;

    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a837d, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(1, 1.6, 1.2);
    scene.add(sun);
    this.scene = scene;

    const gltf = await new GLTFLoader().loadAsync(`/kb/${model.file}`);
    const source = gltf.scene.getObjectByProperty("type", "Mesh");
    // The GLB is Z-up millimetres, like the sheet's thickness axis; turn it Y-up for an orbit view.
    // The same turn maps dimension points: (x, y, z) -> (x, z, -y).
    const geometry = toCreasedNormals(source.geometry.clone().rotateX(-Math.PI / 2), Math.PI / 6);
    const box = new THREE.Box3().setFromBufferAttribute(geometry.getAttribute("position"));
    const radius = box.getSize(new THREE.Vector3()).length() / 2;
    this.box = box;
    this.radius = radius;

    // Section: everything on the camera's side of the plane is cut away, and the cut face is
    // capped and hatched like a section view, using the stencil buffer to find the inside.
    this.plane = new THREE.Plane(new THREE.Vector3(0, 0, -1), 0);
    const clip = [this.plane];
    const part = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      color: FINISH[model.material] ?? 0xbfc3c7, metalness: model.material === "silicone rubber" ? 0 : 0.35, roughness: 0.55,
      clippingPlanes: clip,
    }));
    part.renderOrder = 6;
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25),
      new THREE.LineBasicMaterial({ color: 0x2b2724, clippingPlanes: clip }));
    edges.renderOrder = 6;
    this.stencil = stencilGroup(geometry, this.plane);
    this.cap = new THREE.Mesh(new THREE.PlaneGeometry(radius * 4, radius * 4), hatchMaterial(radius));
    this.cap.renderOrder = 1.1;
    this.cap.onAfterRender = (r) => r.clearStencil();
    scene.add(part, edges, this.stencil, this.cap);

    const grid = new THREE.GridHelper(Math.ceil(radius * 2.4 / 10) * 10, Math.ceil(radius * 2.4 / 10), 0xc9c4bf, 0xdcd8d4);
    grid.position.y = box.min.y - 0.01;
    scene.add(grid);

    this.addDimensions(model);
    this.camera = new THREE.PerspectiveCamera(35, 1, radius / 100, radius * 100);
    this.controls = new OrbitControls(this.camera, renderer.domElement);

    this.setupSection(model);
    this.listen();

    const resize = () => {
      if (!this.root.isConnected) return observer.disconnect(), renderer.dispose();
      const { clientWidth: w, clientHeight: h } = this.root;
      renderer.setSize(w, h);
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
      if (!this.placed) this.home();  // framing depends on the pane's shape
      this.draw();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(this.root);
    this.controls.addEventListener("change", () => this.draw());
    resize();
  }

  home() {
    // Frame the part with its dimension lines, which stand off its edges.
    const view = this.box.clone();
    for (const d of this.dims) view.expandByPoint(d.ends[0]).expandByPoint(d.ends[1]);
    const r = view.getSize(new THREE.Vector3()).length() / 2;
    // Far enough that the bounding sphere fits the narrower of the two fields of view.
    const half = THREE.MathUtils.degToRad(this.camera.fov / 2);
    const narrow = Math.min(half, Math.atan(Math.tan(half) * this.camera.aspect));
    const target = view.getCenter(new THREE.Vector3());
    // A long, thin part (the wiper) is looked at more squarely, or its far end shrinks to nothing.
    const size = view.getSize(new THREE.Vector3());
    const direction = size.x > 4 * size.z ? new THREE.Vector3(0.35, 0.9, 2.0) : new THREE.Vector3(1.5, 1.3, 2.0);
    this.glide(target, target.clone().add(direction.setLength((r / Math.sin(narrow)) * 1.08)));  // room for the labels
  }

  // Bring a dimension close enough to read, keeping the direction it is being looked at from.
  focus(indices) {
    const ends = this.dims.filter((d) => indices.has(d.index)).flatMap((d) => d.ends);
    if (!ends.length) return;
    const view = new THREE.Box3().setFromPoints(ends);
    const target = view.getCenter(new THREE.Vector3());
    const distance = Math.max(view.getSize(new THREE.Vector3()).length() * 2.5, this.radius * 0.35);
    const from = this.camera.position.clone().sub(this.controls.target).setLength(distance);
    this.glide(target, target.clone().add(from));
  }

  glide(target, position) {
    // A short ease, so the eye can follow where it went; instant on the first frame.
    const start = { target: this.controls.target.clone(), position: this.camera.position.clone() };
    const first = !this.placed;
    this.placed = true;
    const began = performance.now();
    const step = (now) => {
      const t = first ? 1 : Math.min((now - began) / 320, 1);
      const k = 1 - (1 - t) ** 3;
      this.controls.target.lerpVectors(start.target, target, k);
      this.camera.position.lerpVectors(start.position, position, k);
      this.controls.update();
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  draw() {
    this.renderer.render(this.scene, this.camera);
    const { clientWidth: w, clientHeight: h } = this.root;
    const p = new THREE.Vector3();
    // Labels go where their lines are; one that would cover another steps down until it is clear.
    // A lit label is placed first, so it is the one that stays on its line.
    const placed = [];
    const order = [...this.dims].sort((a, b) => b.label.classList.contains("lit") - a.label.classList.contains("lit"));
    for (const d of order) {
      p.copy(d.mid).project(this.camera);
      const { offsetWidth: lw, offsetHeight: lh } = d.label;
      const box = { x: ((p.x + 1) / 2) * w - lw / 2, y: ((1 - p.y) / 2) * h - lh / 2, w: lw, h: lh };
      for (let tries = 0; tries < 6 && placed.some((o) => overlaps(o, box)); tries++) box.y += lh + 2;
      placed.push(box);
      d.label.style.transform = `translate(${box.x}px, ${box.y}px)`;
    }
  }

  // --- dimensions ---------------------------------------------------------------

  addDimensions(model) {
    const layer = this.root.querySelector(".dims");
    this.group = new THREE.Group();
    model.dimensions.forEach((d, index) => {
      if (!d.at) return;
      const [a, b, off] = [d.at.a, d.at.b, d.at.offset].map(([x, y, z]) => new THREE.Vector3(x, z, -y));
      const a2 = a.clone().add(off), b2 = b.clone().add(off);
      const at = d.at.label ?? 0.5;
      const mid = a2.clone().lerp(b2, at);
      // Drawn over the part, as dimensions are on a sheet, so a line behind a face stays readable.
      const ink = { color: INK.normal, transparent: true, depthTest: false };
      const materials = [new THREE.LineBasicMaterial(ink), new THREE.MeshBasicMaterial(ink)];
      const points = off.lengthSq() > 0 ? [a, a2, b, b2, a2, b2] : [a2, b2];
      if (at > 1) points.push(b2, mid);
      if (at < 0) points.push(a2, mid);
      const lines = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(points), materials[0]);
      const arrows = [arrow(a2, b2, this.radius, materials[1]), arrow(b2, a2, this.radius, materials[1])];
      const group = new THREE.Group().add(lines, ...arrows);
      group.traverse((o) => (o.renderOrder = 10));
      this.group.add(group);

      const label = document.createElement("button");
      label.type = "button";
      label.className = "dim-label";
      label.dataset.dim = index;
      label.textContent = `${d.at.symbol}${decimal(d.value)}`;
      label.title = d.name;
      layer.append(label);
      this.dims.push({ index, materials, label, ends: [a2, b2], mid });
    });
    this.scene.add(this.group);
  }

  highlight(indices) {
    const any = indices.size > 0;
    for (const d of this.dims) {
      const lit = indices.has(d.index);
      for (const m of d.materials) {
        m.color.setHex(lit ? INK.lit : INK.normal);
        m.opacity = any && !lit ? 0.3 : 1;
      }
      d.label.classList.toggle("lit", lit);
      d.label.classList.toggle("faded", any && !lit);
    }
    this.draw();
  }

  // --- section ------------------------------------------------------------------

  setupSection(model) {
    // The slider is in the model's own Y, which the turn to Y-up maps onto -Z.
    this.range = this.root.querySelector(".section-range input");
    this.range.min = (-this.box.max.z).toFixed(1);
    this.range.max = (-this.box.min.z).toFixed(1);
    this.range.value = String(model.section);
    this.range.addEventListener("input", () => this.cutAt(Number(this.range.value)));
    this.section(false);
  }

  section(on) {
    this.sectioned = on;
    this.root.querySelector("[data-act=section]").setAttribute("aria-pressed", String(on));
    this.root.querySelector(".section-range").hidden = !on;
    this.stencil.visible = this.cap.visible = on;
    if (on) this.cutAt(Number(this.range.value));
    else this.plane.constant = this.radius * 10;
    this.draw();
  }

  cutAt(y) {
    // Keep world z <= -y: the half away from the default camera, so the cut face looks at you.
    this.plane.constant = -y;
    this.plane.coplanarPoint(this.cap.position);
    this.cap.lookAt(this.cap.position.clone().sub(this.plane.normal));
    this.draw();
  }

  // --- events -------------------------------------------------------------------

  listen() {
    this.root.addEventListener("click", (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "section") this.section(!this.sectioned);
      if (act === "dims") {
        const on = !this.group.visible;
        this.group.visible = on;
        this.root.classList.toggle("no-dims", !on);
        e.target.setAttribute("aria-pressed", String(on));
        this.draw();
      }
      if (act === "fit") this.home();
      const label = e.target.closest(".dim-label");
      if (label) this.onPick(Number(label.dataset.dim));
    });
    const layer = this.root.querySelector(".dims");
    layer.addEventListener("pointerover", (e) => {
      const label = e.target.closest(".dim-label");
      if (label) this.onHover(Number(label.dataset.dim));
    });
    layer.addEventListener("pointerout", (e) => {
      if (e.target.closest(".dim-label") && !e.relatedTarget?.closest?.(".dim-label")) this.onHover(null);
    });
  }
}

// What a model was built from, as a table the panel links to the sheet and the model.
export function modelNotes(model) {
  const m = model.mass;
  const sign = m.difference_percent > 0 ? "+" : "";
  return html`
    <h3>Built from</h3>
    <table class="facts dims-table">${model.dimensions.map((d, i) => html`<tr data-dim="${i}" class="${d.at || d.region ? "clickable" : ""}">
      <th>${d.name}</th><td class="mono">${size(d)}</td>
      <td>${d.cite ? raw(chip(d.cite)) : ""}<span class="muted">${d.cite ? (d.note ? ` ${d.note}` : "") : d.note || HOW[d.how]}</span></td></tr>`)}</table>
    <h3 style="margin-top:16px">Mass check</h3>
    <p style="margin:0 0 4px">Volume ${fmt(m.volume_mm3 / 1000, 2)} cm³ × ${fmt(model.density, 2)} g/cm³ = <strong>${fmt(m.computed_g, 1)} g</strong>.
      The title block says ${fmt(m.sheet_g, 1)} g ${raw(chip(m.sheet_cite))}, a difference of ${sign}${fmt(m.difference_percent, 2)} %.</p>
    <p class="muted" style="margin:0">Density: ${model.material}, ${model.density_basis}.</p>
    ${model.assumptions.length ? html`<h3 style="margin-top:16px">Assumptions</h3><ul>${model.assumptions.map((a) => html`<li>${a}</li>`)}</ul>` : ""}
    <h3 style="margin-top:16px">Not modelled</h3><ul>${["threads, chamfers and tolerances", ...model.omitted].map((a) => html`<li>${a}</li>`)}</ul>
    <p style="margin:16px 0 0"><a href="/kb/${model.file}" download>Download the mesh (GLB, millimetres)</a></p>`;
}

// --- drawing helpers --------------------------------------------------------------

function arrow(tip, from, radius, material) {
  const length = Math.min(radius * 0.02, tip.distanceTo(from) * 0.2);
  const cone = new THREE.Mesh(new THREE.ConeGeometry(length * 0.3, length, 12), material);
  const direction = tip.clone().sub(from).normalize();
  cone.position.copy(tip).addScaledVector(direction, -length / 2);
  cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
  return cone;
}

function stencilGroup(geometry, plane) {
  // Count how many surfaces each pixel is behind: inside the solid the back and front faces
  // do not cancel, and that is where the cap is drawn.
  const group = new THREE.Group();
  for (const [side, op] of [[THREE.BackSide, THREE.IncrementWrapStencilOp], [THREE.FrontSide, THREE.DecrementWrapStencilOp]]) {
    const material = new THREE.MeshBasicMaterial({
      side, clippingPlanes: [plane], depthWrite: false, depthTest: false, colorWrite: false,
      stencilWrite: true, stencilFunc: THREE.AlwaysStencilFunc, stencilFail: op, stencilZFail: op, stencilZPass: op,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.renderOrder = 1;
    group.add(mesh);
  }
  return group;
}

function hatchMaterial(radius) {
  // 45° hatching, as a section view draws a cut surface.
  const size = 64;
  const canvas = Object.assign(document.createElement("canvas"), { width: size, height: size });
  const g = canvas.getContext("2d");
  g.fillStyle = "#dcd8d3";
  g.fillRect(0, 0, size, size);
  g.strokeStyle = "#57534e";
  g.lineWidth = 3;
  for (const shift of [-size, 0, size]) {
    g.beginPath();
    g.moveTo(shift, size);
    g.lineTo(shift + size, 0);
    g.stroke();
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(radius * 4 / (radius * 0.05), radius * 4 / (radius * 0.05));
  texture.colorSpace = THREE.SRGBColorSpace;
  return new THREE.MeshBasicMaterial({
    map: texture, stencilWrite: true, stencilRef: 0, stencilFunc: THREE.NotEqualStencilFunc,
    stencilFail: THREE.ReplaceStencilOp, stencilZFail: THREE.ReplaceStencilOp, stencilZPass: THREE.ReplaceStencilOp,
  });
}

const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const fmt = (n, digits) => n.toLocaleString("da-DK", { minimumFractionDigits: digits, maximumFractionDigits: digits });
// The sheet's own style: a decimal comma, one decimal unless the value needs two.
const decimal = (n) => fmt(n, Math.round(n * 10) === n * 10 ? 1 : 2);
const size = (d) => (d.name.includes("spacing") ? `${fmt(d.value, 0)}°` : `${d.at?.symbol || ""}${decimal(d.value)} mm`);
