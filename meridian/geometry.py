"""3D reconstructions of five clean, simple sheets, built only from what each sheet says.

These are reconstructions from 2D evidence, not CAD. Each part is a short
function that takes every dimension from an observation, so the source sits
next to the number in the code and in the app. Where the sheet does not
dimension something (the wiper's hole positions), it is measured off the
sheet's vector geometry at the sheet's own scale, and recorded as measured.

Every model is then checked against physics: its volume times the material's
density, against the weight SolidWorks printed in the title block. Mass does
not depend on where a hole is, only on how big it is, so it checks sizes and
thicknesses, which are the things most easily misread.

Threads, chamfers, edge breaks and tolerances are not modelled. Tapped holes
are modelled at their tap-drill size, which is what removes material.

Each dimension also says where to draw it on the model (`show`) and where it
sits on the sheet (`region`), so the app can point from one to the other.
Coordinates are the solid's own: millimetres, Z along the thickness, centred.
"""

import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

import manifold3d as mf
import numpy as np
import pymupdf
import trimesh

from meridian import config
from meridian.evidence import Observation

SEGMENTS = 256  # a 256-gon loses 0.01% of a circle's area; small next to any tolerance on these sheets
MM = 72 / 25.4  # PDF points per millimetre at 1:1

# Densities in g/cm³. Aluminium and stainless are handbook values for the named grades;
# silicone rubber varies by compound, so its value is an assumption and says so.
DENSITY = {
    "EN AW-5005": (2.70, "handbook value for EN AW-5005"),
    "AISI 316": (8.00, "handbook value for AISI 316"),
    "silicone rubber": (1.25, "typical for silicone rubber; the compound is not specified"),
}


@dataclass
class Dimension:
    name: str
    value: float
    cite: str | None
    how: str          # "callout", "limit", "measured" or "as drawn"
    note: str = ""
    at: dict | None = None        # a dimension line on the model: from a to b, drawn at an offset
    region: list | None = None    # where it is on the sheet, PDF points; the cited callout's box unless measured


@dataclass
class Reconstruction:
    drawing: str
    name: str
    material: str
    density: float
    density_basis: str
    dimensions: list[Dimension] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)
    mass: dict = field(default_factory=dict)
    file: str = ""
    section: float = 0.0  # default position of the section cut, along Y: through the holes worth seeing
    extent: list[float] = field(default_factory=list)  # bounding box in mm, x y z


class Sheet:
    """Reads dimensions for one reconstruction and remembers where each came from."""

    def __init__(self, drawing: str, observations: dict[str, Observation], record: Reconstruction):
        self.drawing = drawing
        self.obs = observations
        self.record = record

    def dim(self, name: str, cite: str, key: str = "value", pick: Callable[[object], float] | None = None,
            how: str = "callout", note: str = "") -> float:
        o = self.obs[cite]
        if o.subject != self.drawing:
            raise ValueError(f"{cite} is not on {self.drawing}")
        raw = o.parsed[key]
        value = pick(raw) if pick else raw
        self.record.dimensions.append(Dimension(name, float(value), cite, how, note))
        return float(value)

    def measured(self, name: str, value: float, note: str, region: list | None = None) -> float:
        self.record.dimensions.append(Dimension(name, round(value, 2), None, "measured", note, region=region))
        return value

    def as_drawn(self, name: str, value: float, note: str) -> float:
        self.record.dimensions.append(Dimension(name, value, None, "as drawn", note))
        return value

    def show(self, name: str, a, b, offset=(0, 0, 0), symbol: str = "", label: float = 0.5) -> None:
        """Where a dimension is drawn on the model, as a drafter would: extension lines from a and b out to
        the offset, and the dimension line between them. `symbol` is printed before the value (Ø, R).
        `label` is where the value sits along the line, 0 at a and 1 at b; beyond either end, the line
        is carried out to it, as a drafter does for a feature too small to write inside."""
        dim = next(d for d in self.record.dimensions if d.name == name)
        dim.at = {"a": [round(v, 3) for v in a], "b": [round(v, 3) for v in b],
                  "offset": [round(v, 3) for v in offset], "symbol": symbol, "label": label}

    def assume(self, text: str) -> None:
        self.record.assumptions.append(text)

    def omit(self, *features: str) -> None:
        self.record.omitted.extend(features)


# --- solids -------------------------------------------------------------------

def box(x: float, y: float, z: float) -> mf.Manifold:
    return mf.Manifold.cube([x, y, z], center=True)


def disc(diameter: float, thickness: float) -> mf.Manifold:
    return mf.Manifold.cylinder(thickness, diameter / 2, -1, SEGMENTS, center=True)


def hole_z(diameter: float, x: float, y: float, depth: float = 1000) -> mf.Manifold:
    """A through hole along Z (deep enough to pass any of these parts)."""
    return mf.Manifold.cylinder(depth, diameter / 2, -1, SEGMENTS, center=True).translate([x, y, 0])


def countersink(top_diameter: float, hole_diameter: float, angle: float, x: float, y: float, top: float) -> mf.Manifold:
    depth = (top_diameter - hole_diameter) / 2 / math.tan(math.radians(angle / 2))
    cone = mf.Manifold.cylinder(depth, hole_diameter / 2, top_diameter / 2, SEGMENTS)
    return cone.translate([x, y, top - depth])


def counterbore(diameter: float, depth: float, x: float, y: float, top: float) -> mf.Manifold:
    return mf.Manifold.cylinder(depth, diameter / 2, -1, SEGMENTS).translate([x, y, top - depth])


def polar(radius: float, angles: list[float]) -> list[tuple[float, float]]:
    return [(radius * math.cos(math.radians(a)), radius * math.sin(math.radians(a))) for a in angles]


def across(x: float, y: float, z: float, diameter: float, angle: float = 0.0) -> tuple[tuple, tuple]:
    """The two ends of a diameter through (x, y) at height z, at `angle` degrees from X."""
    dx, dy = diameter / 2 * math.cos(math.radians(angle)), diameter / 2 * math.sin(math.radians(angle))
    return (x - dx, y - dy, z), (x + dx, y + dy, z)


# --- the five parts -------------------------------------------------------------

def recoater_mount_block(s: Sheet) -> mf.Manifold:
    length = s.dim("length", "D-012.p1.a07")
    width = s.dim("width", "D-012.p1.a01", note="+0,1 / -0,5; nominal used")
    thickness = s.dim("thickness", "D-012.p1.a02", note="±1,0; nominal used")
    drill = s.dim("tap drill, M6 holes", "D-012.p1.a03", key="diameter")
    face_offset = s.dim("face holes from centre", "D-012.p1.a05")
    side_offset = s.dim("side holes from centre", "D-012.p1.a06")
    from_edge = s.dim("face holes from the long edge", "D-012.p1.a04", note="±0,1; half the width, so on the centre line")
    s.omit("M6 threads (modelled at the Ø5,0 tap drill)", "edge breaks")
    s.assume("The side holes sit on the centre line of the 15 mm face, as drawn; the sheet does not dimension it.")

    x0, y0, z0 = length / 2, width / 2, thickness / 2
    s.show("length", (-x0, -y0, -z0), (x0, -y0, -z0), (0, -16, 0))
    s.show("width", (x0, -y0, z0), (x0, y0, z0), (8, 0, 0))
    s.show("thickness", (x0, -y0, -z0), (x0, -y0, z0), (0, -8, 0))
    s.show("tap drill, M6 holes", *across(face_offset, from_edge - y0, z0, drill, 90), symbol="Ø")
    s.show("face holes from centre", (0, 0, z0), (face_offset, 0, z0))
    s.show("side holes from centre", (0, -y0, 0), (-side_offset, -y0, 0))
    s.show("face holes from the long edge", (-face_offset, -y0, z0), (-face_offset, from_edge - y0, z0))

    solid = box(length, width, thickness)
    for x in (-face_offset, face_offset):
        solid -= hole_z(drill, x, from_edge - width / 2)
    side = mf.Manifold.cylinder(1000, drill / 2, -1, SEGMENTS, center=True).rotate([90, 0, 0])
    for x in (-side_offset, side_offset):
        solid -= side.translate([x, 0, 0])
    return solid


def silicone_wiper(s: Sheet) -> mf.Manifold:
    length = s.dim("length", "D-015.p1.a02")
    width = s.dim("width", "D-015.p1.a03")
    thickness = s.dim("thickness", "D-015.p1.a01")
    hole = s.dim("hole diameter", "D-015.p1.a04", key="diameter")
    centres, view = _hole_centres("D-015", length, width)
    s.measured("first hole from the end", centres[0][0], "measured on the sheet's vector geometry at 1:1", view)
    pitch = s.measured("hole pitch", (centres[-1][0] - centres[0][0]) / (len(centres) - 1),
                       "measured; matches the 35,7 pitch between D-013's eight M3 holes, where the wiper is clamped", view)
    s.measured("holes off the centre line", abs(centres[0][1]), "measured; the row sits 5 mm from one long edge", view)
    s.omit("the cut edge finish of the waterjet-cut sheet")

    x0, y0, z0 = length / 2, width / 2, thickness / 2
    first, row = centres[0]
    chain = (0, -y0 - 3 - row, 0)  # the hole positions, chained along a line just off the front edge
    s.show("length", (-x0, -y0, z0), (x0, -y0, z0), (0, -12, 0))
    s.show("width", (x0, -y0, z0), (x0, y0, z0), (6, 0, 0))
    s.show("thickness", (x0, -y0, -z0), (x0, -y0, z0), (0, -6, 0))
    s.show("hole diameter", *across(first - x0, row, z0, hole, 90), symbol="Ø", label=2.6)
    s.show("first hole from the end", (-x0, row, z0), (first - x0, row, z0), chain)
    s.show("hole pitch", (first - x0, row, z0), (first + pitch - x0, row, z0), chain)
    s.show("holes off the centre line", (centres[2][0] - x0, 0, z0), (centres[2][0] - x0, row, z0))
    s.record.section = row

    solid = box(length, width, thickness)
    for x, y in centres:
        solid -= hole_z(hole, x - length / 2, y)
    return solid


def build_base_ring(s: Sheet) -> mf.Manifold:
    outer = s.dim("outer diameter", "D-025.p1.a02", key="diameter", note="±0,2")
    inner = s.dim("inner diameter", "D-025.p1.a03", key="diameter", note="+0,3 / 0,0")
    thickness = s.dim("thickness", "D-025.p1.a01", key="limits", pick=max, how="limit",
                      note="the sheet allows 2,0 to 3,0; the title-block weight matches 3,0")
    hole = s.dim("hole diameter", "D-025.p1.a05", key="diameter")
    sink = s.dim("countersink diameter", "D-025.p1.a05", key="countersink", pick=lambda c: c["size"])
    pitch_radius = s.dim("hole circle radius", "D-025.p1.a04", key="radius")
    s.as_drawn("hole spacing", 45.0, "eight holes evenly spaced, as drawn; the angle is not dimensioned")

    z0 = thickness / 2
    sink_depth = (sink - hole) / 2  # a 90° countersink is as deep as it is wide at the rim, per side
    hx, hy = polar(pitch_radius, [-90.0])[0]  # the hole nearest the default view, which the default section cuts
    s.show("outer diameter", *across(0, 0, z0, outer, 70), symbol="Ø", label=0.82)  # between holes, not across one
    s.show("inner diameter", *across(0, 0, z0, inner), symbol="Ø")
    s.show("thickness", (outer / 2, 0, -z0), (outer / 2, 0, z0), (12, 0, 0))
    s.show("hole circle radius", (0, 0, z0), (*polar(pitch_radius, [-45.0])[0], z0), symbol="R")
    s.show("countersink diameter", *across(hx, hy, z0, sink, 90), symbol="Ø", label=-1.2)
    s.show("hole diameter", *across(hx, hy, z0 - sink_depth, hole), symbol="Ø", label=4.5)
    s.record.section = round(hy, 2)

    solid = disc(outer, thickness) - disc(inner, thickness + 2)
    for x, y in polar(pitch_radius, [i * 45.0 for i in range(8)]):
        solid -= hole_z(hole, x, y)
        solid -= countersink(sink, hole, 90, x, y, thickness / 2)
    return solid


def build_plate(s: Sheet) -> mf.Manifold:
    diameter = s.dim("diameter", "D-026.p1.a02", key="diameter")
    low, high = s.obs["D-026.p1.a01"].parsed["limits"]
    thickness = s.dim("thickness", "D-026.p1.a01", key="limits", pick=lambda l: (l[0] + l[1]) / 2, how="limit",
                      note=f"the sheet gives a range, {low:g} to {high:g}; the title-block weight matches its midpoint, 20")
    hole = s.dim("through hole", "D-026.p1.a04", key="diameter")
    bore = s.dim("counterbore diameter", "D-026.p1.a04", key="counterbore", pick=lambda c: c["diameter"])
    bore_depth = s.dim("counterbore depth", "D-026.p1.a04", key="counterbore", pick=lambda c: c["depth"])
    pitch_radius = s.dim("hole circle radius", "D-026.p1.a03", key="radius")
    s.as_drawn("hole spacing", 120.0, "three holes 120° apart, as drawn")
    s.assume("Counterbores open on the top face, which the view shows; the sheet does not name a side.")
    s.omit("the parallelism tolerance to datum A")

    z0 = thickness / 2
    hx, hy = polar(pitch_radius, [300.0])[0]  # the hole nearest the default view, which the default section cuts
    s.show("diameter", *across(0, 0, z0, diameter, 90), symbol="Ø")
    s.show("thickness", (diameter / 2, 0, -z0), (diameter / 2, 0, z0), (14, 0, 0))
    s.show("hole circle radius", (0, 0, z0), (-pitch_radius, 0, z0), symbol="R")
    s.show("counterbore diameter", *across(hx, hy, z0, bore), symbol="Ø")
    s.show("counterbore depth", (hx - bore / 2, hy, z0), (hx - bore / 2, hy, z0 - bore_depth))
    s.show("through hole", *across(hx, hy, -z0, hole), symbol="Ø")
    s.record.section = round(hy, 2)

    solid = disc(diameter, thickness)
    for x, y in polar(pitch_radius, [60.0, 180.0, 300.0]):
        solid -= hole_z(hole, x, y)
        solid -= counterbore(bore, bore_depth, x, y, thickness / 2 + 0.001)
    return solid


def heating_element_plate(s: Sheet) -> mf.Manifold:
    centres = s.dim("distance between end centres", "D-028.p1.a03")
    radius = s.dim("end radius", "D-028.p1.a02", key="radius")
    width = s.dim("width", "D-028.p1.a04")
    thickness = s.dim("thickness", "D-028.p1.a01", key="limits", pick=min, how="limit",
                      note="the sheet allows 2,0 to 3,0; the title-block weight matches 2,0")
    small = s.dim("end holes", "D-028.p1.a05", key="diameter")
    middle = s.dim("centre hole", "D-028.p1.a06", key="diameter", note="±0,15")
    if abs(2 * radius - width) > 0.01:
        raise ValueError("D-028: the end radius and the width disagree")
    s.assume("The end holes are concentric with the end radii and the Ø8 hole is central, as drawn.")

    x0, z0 = centres / 2, thickness / 2
    s.show("distance between end centres", (-x0, 0, z0), (x0, 0, z0), (0, -radius - 3, 0))
    s.show("end radius", (x0, 0, z0), (x0 + radius * math.cos(math.radians(-45)), radius * math.sin(math.radians(-45)), z0), symbol="R")
    between = (-x0 + small / 2 - middle / 2) / 2  # clear of both holes
    s.show("width", (between, -radius, z0), (between, radius, z0))
    s.show("thickness", (x0 + radius, 0, -z0), (x0 + radius, 0, z0), (3, 0, 0))
    s.show("end holes", *across(-x0, 0, z0, small), symbol="Ø")
    s.show("centre hole", *across(0, 0, z0, middle, 45), symbol="Ø")

    end = mf.Manifold.cylinder(thickness, radius, -1, SEGMENTS, center=True)
    solid = box(centres, width, thickness) + end.translate([-centres / 2, 0, 0]) + end.translate([centres / 2, 0, 0])
    for x in (-centres / 2, centres / 2):
        solid -= hole_z(small, x, 0)
    return solid - hole_z(middle, 0, 0)


PARTS: dict[str, tuple[Callable[[Sheet], mf.Manifold], str]] = {
    "D-012": (recoater_mount_block, "EN AW-5005"),
    "D-015": (silicone_wiper, "silicone rubber"),
    "D-025": (build_base_ring, "EN AW-5005"),
    "D-026": (build_plate, "AISI 316"),
    "D-028": (heating_element_plate, "EN AW-5005"),
}


# --- building -------------------------------------------------------------------

def build_all(observations: list[Observation], names: dict[str, str]) -> dict[str, dict]:
    by_id = {o.id: o for o in observations}
    out_dir = config.KB / "models"
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {}
    for drawing, (make, material) in PARTS.items():
        density, basis = DENSITY[material]
        record = Reconstruction(drawing, names[drawing], material, density, basis)
        solid = make(Sheet(drawing, by_id, record))
        for d in record.dimensions:
            if d.cite and d.region is None:
                d.region = by_id[d.cite].source.bbox
        record.mass = _mass_check(drawing, solid, density, by_id)
        box = solid.bounding_box()
        record.extent = [round(hi - lo, 1) for lo, hi in zip(box[:3], box[3:])]
        record.file = f"models/{drawing}.glb"
        _export(solid, out_dir / f"{drawing}.glb")
        index[drawing] = asdict(record)
    (out_dir / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n")
    return index


def _mass_check(drawing: str, solid: mf.Manifold, density: float, obs: dict[str, Observation]) -> dict:
    weight = obs[f"{drawing}.p1.weight"]
    printed = weight.parsed["grams"]
    computed = solid.volume() / 1000 * density
    return {
        "volume_mm3": round(solid.volume(), 1),
        "computed_g": round(computed, 1),
        "sheet_g": printed,
        "sheet_cite": weight.id,
        "difference_percent": round(100 * (computed - printed) / printed, 2),
    }


def _export(solid: mf.Manifold, path) -> None:
    mesh = solid.to_mesh()
    tm = trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts), process=False)
    path.write_bytes(tm.export(file_type="glb"))


def _hole_centres(drawing: str, length: float, width: float) -> tuple[list[tuple[float, float]], list[float]]:
    """Hole centres in mm, measured off the view whose outline is length x width at the sheet's scale,
    and that view's box on the sheet.

    SolidWorks writes a view's outline and its holes as one path; the holes are the small
    closed loops inside it. Positions are taken from the left end and the centre line.
    """
    with pymupdf.open(config.DRAWINGS / f"{drawing}.pdf") as doc:
        page = doc[0]
        for d in page.get_drawings():
            r = d["rect"]
            if abs(r.width / MM - length) < 0.5 and abs(r.height / MM - width) < 0.5:
                loops = _loops(d["items"])
                centres = []
                for loop in loops:
                    xs = [p.x for p in loop]
                    ys = [p.y for p in loop]
                    if len(loop) > 8 and max(xs) - min(xs) < 10 * MM:
                        centres.append((((max(xs) + min(xs)) / 2 - r.x0) / MM, ((max(ys) + min(ys)) / 2 - (r.y0 + r.y1) / 2) / MM))
                view = [round(v, 1) for v in (r.x0, r.y0, r.x1, r.y1)]
                return sorted((round(x, 2), round(y, 2)) for x, y in centres), view
    raise ValueError(f"no {length} x {width} view found on {drawing}")


def _loops(items: list) -> list[list]:
    loops, current = [], []
    for item in items:
        a, b = item[1], item[2]
        if current and (abs(a.x - current[-1].x) > 0.01 or abs(a.y - current[-1].y) > 0.01):
            loops.append(current)
            current = []
        if not current:
            current.append(a)
        current.append(b)
    if current:
        loops.append(current)
    return loops
