// The 3D tab: an orbitable reconstruction, labelled as one, with everything it was built from.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { toCreasedNormals } from "three/addons/utils/BufferGeometryUtils.js";
import { html, raw, mount } from "./dom.js";
import { chip } from "./render.js";

const FINISH = { "EN AW-5005": 0xc4c8cc, "AISI 316": 0xa7aaad, "silicone rubber": 0xb8644a };
const HOW = { measured: "measured off the sheet", "as drawn": "as drawn, not dimensioned", limit: "chosen within a limit" };

export class ModelViewer {
  constructor(root, notes) {
    this.root = root;
    this.notes = notes;
  }

  async show(model) {
    this.describe(model);
    this.root.insertAdjacentHTML("beforeend",
      `<div class="model-label">Reconstruction from the 2D drawing, not native CAD. Threads, chamfers and tolerances are not modelled.</div>`);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setClearColor(0xeceae8);
    this.root.prepend(renderer.domElement);

    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a837d, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(1, 1.6, 1.2);
    scene.add(sun);

    const gltf = await new GLTFLoader().loadAsync(`/kb/${model.file}`);
    const source = gltf.scene.getObjectByProperty("type", "Mesh");
    // The GLB is Z-up millimetres, like the sheet's thickness axis; turn it Y-up for an orbit view.
    const geometry = toCreasedNormals(source.geometry.clone().rotateX(-Math.PI / 2), Math.PI / 6);
    const part = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      color: FINISH[model.material] ?? 0xbfc3c7, metalness: model.material === "silicone rubber" ? 0 : 0.35, roughness: 0.55,
    }));
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25),
      new THREE.LineBasicMaterial({ color: 0x2b2724 }));
    scene.add(part, edges);

    const box = new THREE.Box3().setFromObject(part);
    const size = box.getSize(new THREE.Vector3());
    const radius = size.length() / 2;
    const grid = new THREE.GridHelper(Math.ceil(radius * 2.4 / 10) * 10, Math.ceil(radius * 2.4 / 10), 0xc9c4bf, 0xdcd8d4);
    grid.position.y = box.min.y - 0.01;
    scene.add(grid);

    const camera = new THREE.PerspectiveCamera(35, 1, radius / 100, radius * 100);
    camera.position.set(radius * 1.5, radius * 1.3, radius * 2.0);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(box.getCenter(new THREE.Vector3()));
    controls.update();

    const draw = () => renderer.render(scene, camera);
    const resize = () => {
      if (!this.root.isConnected) return observer.disconnect(), renderer.dispose();
      const { clientWidth: w, clientHeight: h } = this.root;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      draw();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(this.root);
    controls.addEventListener("change", draw);
    resize();
  }

  describe(model) {
    const m = model.mass;
    const sign = m.difference_percent > 0 ? "+" : "";
    mount(this.notes, html`
      <h3>Mass check</h3>
      <p style="margin:0 0 4px">Volume ${fmt(m.volume_mm3 / 1000, 2)} cm³ × ${fmt(model.density, 2)} g/cm³ = <strong>${fmt(m.computed_g, 1)} g</strong>.
        The title block says ${fmt(m.sheet_g, 1)} g ${raw(chip(m.sheet_cite))}, a difference of ${sign}${fmt(m.difference_percent, 2)} %.</p>
      <p class="muted" style="margin:0 0 16px">Density: ${model.material}, ${model.density_basis}.</p>
      <h3>Built from</h3>
      <table class="facts">${model.dimensions.map((d) => html`<tr>
        <th>${d.name}</th><td class="mono">${fmt(d.value, d.value % 1 ? 2 : 0)} ${d.name.includes("spacing") ? "°" : "mm"}</td>
        <td>${d.cite ? raw(chip(d.cite)) : html`<span class="muted">${HOW[d.how]}</span>`}${d.note ? html` <span class="muted">${d.note}</span>` : ""}</td></tr>`)}</table>
      ${model.assumptions.length ? html`<h3 style="margin-top:16px">Assumptions</h3><ul>${model.assumptions.map((a) => html`<li>${a}</li>`)}</ul>` : ""}
      ${model.omitted.length ? html`<h3 style="margin-top:16px">Not modelled</h3><ul>${model.omitted.map((a) => html`<li>${a}</li>`)}</ul>` : ""}
      <p style="margin:16px 0 0"><a href="/kb/${model.file}" download>Download the mesh (GLB, millimetres)</a></p>`);
  }
}

const fmt = (n, digits) => n.toLocaleString("da-DK", { minimumFractionDigits: digits, maximumFractionDigits: digits });
