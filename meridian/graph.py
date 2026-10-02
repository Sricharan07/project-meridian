"""The knowledge as a graph: parts, drawings, subsystems, materials and suppliers, and how they connect.

Nothing here is stored. The graph is derived from the knowledge base every time it loads, so an
accepted correction reshapes it the same way it reshapes answers, and every edge carries the
observations that assert it. An edge with no evidence cannot be built.

Node ids reuse the references the rest of the system uses (BOM.30, D-011), plus three kinds of
their own: family:Box, material:aluminium, supplier:misumi.

Edge kinds:
  part_of     a BOM row's family, or a drawing's subsystem from the manifest
  documents   a drawing documents a BOM row (linked, probable or ambiguous)
  interfaces  stated in the BOM, read off a diagram, or inferred from mating fits
  made_of     a material named by a BOM row, or by a drawing's title block
  supplied_by the supplier recorded in the BOM snapshot
"""

import heapq
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from meridian import materials
from meridian.linking import SUBSYSTEM_FAMILY
from meridian.reading import Status

# Moving along an edge costs this much when looking for a path. Physical and documentary edges are
# cheap; sharing a subsystem is weak; sharing a material or a supplier says nothing about how two
# parts connect, so a path never uses them unless asked to.
COST = {"interfaces": 1.0, "documents": 0.25, "part_of": 4.0}
SUBSYSTEM_OF_FAMILY = {family: subsystem for subsystem, family in SUBSYSTEM_FAMILY.items()}


@dataclass
class Node:
    id: str
    kind: str          # part | drawing | family | material | supplier
    label: str
    detail: str = ""


@dataclass
class Edge:
    a: str
    b: str
    kind: str
    label: str
    cites: list[str]
    source: str = ""   # stated | diagram | inferred for interfaces; bom | sheet for made_of
    status: str = ""   # linked | probable | ambiguous for documents; conflict where sources disagree


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def add(self, node: Node) -> str:
        self.nodes.setdefault(node.id, node)
        return node.id

    def connect(self, edge: Edge) -> None:
        if not edge.cites:
            raise ValueError(f"an edge needs evidence: {edge.a} {edge.kind} {edge.b}")
        self.edges.append(edge)

    def to_dict(self) -> dict:
        return {"nodes": [asdict(n) for n in self.nodes.values()], "edges": [asdict(e) for e in self.edges]}


def build(kb) -> Graph:
    g = Graph()
    family_of_row: dict[int, str] = {}

    for row in kb.bom_rows:
        ref = f"BOM.{row}"
        name = kb.cell(row, "name")
        family = kb.cell(row, "family")
        kind = kb.cell(row, "type")
        g.add(Node(ref, "part", name.value if name else ref, f"BOM row {row}" + (f" · {kind.value}" if kind and kind.value else "")))
        if family and family.value:
            family_of_row[row] = family.value
            fid = g.add(_family(family.value))
            g.connect(Edge(ref, fid, "part_of", "in", [family.id]))
        if (cell := kb.cell(row, "material")) and (families := (cell.parsed or {}).get("families")):
            for fam in families:
                g.connect(Edge(ref, g.add(_material(fam)), "made_of", cell.value, [cell.id], source="bom"))
        if (cell := kb.cell(row, "supplier")) and cell.value.strip():
            g.connect(Edge(ref, g.add(_supplier(cell.value)), "supplied_by", "recorded in the BOM snapshot", [cell.id]))

    for d, info in kb.sheets.items():
        g.add(Node(d, "drawing", kb.drawing_name(d), f"{info['subsystem']} · {'scanned' if info['degraded'] else 'clean'} sheet"))
        family = SUBSYSTEM_FAMILY.get(info["subsystem"], info["subsystem"])
        g.connect(Edge(d, g.add(_family(family)), "part_of", "in", [f"{d}.subsystem"]))
        link = kb.links[d]
        for row in link.parsed["rows"]:
            g.connect(Edge(d, f"BOM.{row}", "documents", "documents", [link.id], status=link.parsed["status"]))
        material = next((c for c in kb.compare(d) if c["field"] == "material"), None)
        reading = kb.field(d, 1, "material")
        if not reading["value"] or reading["status"] == Status.DISPUTED.value:
            reading = kb.field(d, 1, "note")  # the note stands in only when the field says nothing usable
        found = (materials.read(reading["value"]) or {}).get("families", []) if reading["value"] and reading["status"] != Status.DISPUTED.value else []
        for fam in found:
            g.connect(Edge(d, g.add(_material(fam)), "made_of", reading["value"].split("\n")[0], [reading["cite"]], source="sheet",
                           status="conflict" if material and material["verdict"] == "conflict" else ""))

    for r in kb.relations:
        if not (_known(r.a, g) and _known(r.b, g)):
            continue  # a BOM "Interface with" entry naming no row: kept in the knowledge base, not drawable
        g.connect(Edge(r.a, r.b, "interfaces", r.relation, list(r.evidence), source=r.kind))
    return g


def path(g: Graph, start: str, goal: str, kinds: tuple[str, ...] = ("interfaces", "documents", "part_of")) -> dict:
    """The cheapest chain of evidence from one node to another, using only the given edge kinds."""
    if start not in g.nodes or goal not in g.nodes:
        missing = [n for n in (start, goal) if n not in g.nodes]
        return {"error": f"no node {', '.join(missing)}"}
    adjacent = defaultdict(list)
    for e in g.edges:
        if e.kind in kinds:
            adjacent[e.a].append((e.b, e))
            adjacent[e.b].append((e.a, e))
    best = {start: 0.0}
    came: dict[str, tuple[str, Edge]] = {}
    queue = [(0.0, start)]
    while queue:
        cost, here = heapq.heappop(queue)
        if here == goal:
            break
        if cost > best.get(here, float("inf")):
            continue
        for there, e in adjacent[here]:
            # Family nodes are crossroads, not places: a path may pass through a subsystem only between its parts.
            step = cost + COST.get(e.kind, 2.0) + (2.0 if g.nodes[there].kind == "family" and there != goal else 0.0)
            if step < best.get(there, float("inf")):
                best[there], came[there] = step, (here, e)
                heapq.heappush(queue, (step, there))
    if goal not in came and goal != start:
        return {"from": _brief(g, start), "to": _brief(g, goal), "found": False,
                "note": "No chain of interfaces, drawings or shared subsystems connects these two."}
    hops, at = [], goal
    while at != start:
        before, e = came[at]
        hops.append({"from": _brief(g, before), "to": _brief(g, at), "kind": e.kind, "relation": e.label,
                     "source": e.source, "status": e.status, "cites": e.cites})
        at = before
    hops.reverse()
    weak = [h for h in hops if h["kind"] == "part_of"]
    return {"from": _brief(g, start), "to": _brief(g, goal), "found": True, "hops": hops,
            "note": "Passes through a shared subsystem, which says they belong together, not that they touch." if weak else ""}


def subsystem_links(g: Graph) -> list[dict]:
    """How often parts of one subsystem interface with parts of another, with the evidence for each."""
    home = {}
    for e in g.edges:
        if e.kind == "part_of":
            home.setdefault(e.a, e.b)
    pairs: dict[tuple, list[Edge]] = defaultdict(list)
    for e in g.edges:
        if e.kind != "interfaces":
            continue
        fa, fb = home.get(e.a), home.get(e.b)
        if fa and fb and fa != fb:
            pairs[tuple(sorted((fa, fb)))].append(e)
    return [{"between": [g.nodes[a].label, g.nodes[b].label], "interfaces": len(edges),
             "parts": sorted({f"{g.nodes[e.a].label} – {g.nodes[e.b].label}" for e in edges}),
             "cites": sorted({c for e in edges for c in e.cites})}
            for (a, b), edges in sorted(pairs.items(), key=lambda kv: -len(kv[1]))]


# --- nodes ----------------------------------------------------------------------------------------

def _family(family: str) -> Node:
    subsystem = SUBSYSTEM_OF_FAMILY.get(family)
    if not subsystem:
        return Node(f"family:{family}", "family", family, "BOM family with no drawings")
    return Node(f"family:{family}", "family", subsystem, f"BOM family {family}" if subsystem != family else "")


def _material(family: str) -> Node:
    return Node(f"material:{family}", "material", family)


def _supplier(name: str) -> Node:
    clean = " ".join(name.split())
    return Node(f"supplier:{clean.casefold()}", "supplier", clean)


def _known(ref: str, g: Graph) -> bool:
    return ref in g.nodes


def _brief(g: Graph, ref: str) -> dict:
    n = g.nodes[ref]
    return {"ref": n.id, "name": n.label, "kind": n.kind}
