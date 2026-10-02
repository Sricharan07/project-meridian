// How an observation id reads to a person.
//   D-026.p1.weight            -> D-026 weight
//   D-011.p1.material.vision   -> D-011 material, vision
//   D-023.p1.vision.c06        -> D-023 callout, vision
//   BOM.48.amount              -> BOM 48 amount
//   Zaxis_legend.l03           -> Z-axis diagram

const DIAGRAMS = { Zaxis_legend: "Z-axis diagram", RecoaterLegend: "Recoater diagram", PowderLegend: "Powder diagram" };

export function citeLabel(id) {
  let m;
  if ((m = id.match(/^BOM\.(\d+)\.(.+)$/))) return `BOM ${m[1]} ${m[2].replaceAll("_", " ")}`;
  if ((m = id.match(/^(D-\d{3})\.bom-link$/))) return `${m[1]} link`;
  if ((m = id.match(/^(D-\d{3})\.p(\d+)\.(ocr|vision)\.[ac]\d+$/))) return `${m[1]} callout, ${m[3]}`;
  if ((m = id.match(/^(D-\d{3})\.p(\d+)\.a\d+$/))) return `${m[1]} callout`;
  if ((m = id.match(/^(D-\d{3})\.p(\d+)\.(\w+)\.(ocr|vision)$/))) return `${m[1]} ${m[3]}, ${m[4]}`;
  if ((m = id.match(/^(D-\d{3})\.p(\d+)\.(\w+)$/))) return `${m[1]} ${m[3]}`;
  if ((m = id.match(/^(\w+)\.l\d+$/))) return DIAGRAMS[m[1]] || m[1];
  return id;
}

export const citeTarget = (id) => {
  const drawing = id.match(/^(D-\d{3})\./);
  if (drawing) return { kind: "drawing", ref: drawing[1] };
  const row = id.match(/^BOM\.(\d+)\./);
  if (row) return { kind: "bom", row: Number(row[1]) };
  const diagram = id.match(/^(\w+)\.l\d+$/);
  if (diagram) return { kind: "diagram", name: diagram[1] };
  return { kind: "other" };
};
