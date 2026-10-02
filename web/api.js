async function get(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

async function post(path, body) {
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `${path}: ${response.status}`);
  return response.json();
}

const cache = new Map();
const once = (key, load) => {
  if (!cache.has(key)) cache.set(key, load().catch((e) => { cache.delete(key); throw e; }));
  return cache.get(key);
};

export const api = {
  status: () => once("status", () => get("/api/status")),
  drawings: () => once("drawings", () => get("/api/drawings")),
  bom: () => once("bom", () => get("/api/bom")),
  part: (ref) => once(`part:${ref}`, () => get(`/api/parts/${encodeURIComponent(ref)}`)),
  evidence: (id) => once(`evidence:${id}`, () => get(`/api/evidence/${encodeURIComponent(id)}`)),
  models: () => once("models", () => get("/kb/models/index.json")),
  ask: (question, history) => post("/api/chat", { question, history }),
  forget: (prefix) => [...cache.keys()].filter((k) => k.startsWith(prefix)).forEach((k) => cache.delete(k)),
};
