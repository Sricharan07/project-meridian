"""The graph is derived from the knowledge base, so it can only say what the evidence says."""

import pytest

from meridian import corrections, graph
from meridian.knowledge import KnowledgeBase


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase.load()


def test_every_edge_cites_observations_that_exist(kb):
    g = kb.graph
    assert g.edges
    for e in g.edges:
        assert e.cites, f"{e.a} {e.kind} {e.b} has no evidence"
        assert all(c in kb.obs for c in e.cites), f"{e.a} {e.kind} {e.b} cites something that is not an observation"
        assert e.a in g.nodes and e.b in g.nodes


def test_a_path_is_a_chain_of_cited_steps(kb):
    p = graph.path(kb.graph, "D-015", "D-013")
    assert p["found"]
    assert [h["kind"] for h in p["hops"]] == ["documents", "interfaces", "documents"]
    assert [h["from"]["ref"] for h in p["hops"]][0] == "D-015" and p["hops"][-1]["to"]["ref"] == "D-013"
    assert all(h["cites"] for h in p["hops"])


def test_a_path_never_goes_through_a_shared_material_or_supplier(kb):
    for a, b in [("D-011", "D-026"), ("D-012", "D-028"), ("BOM.84", "D-012")]:
        p = graph.path(kb.graph, a, b)
        assert all(h["kind"] in ("interfaces", "documents", "part_of") for h in p.get("hops", []))


def test_a_step_through_a_subsystem_is_called_weak(kb):
    p = graph.path(kb.graph, "D-011", "D-026")
    assert p["found"] and any(h["kind"] == "part_of" for h in p["hops"])
    assert "not that they touch" in p["note"]


def test_an_accepted_correction_reshapes_the_graph(tmp_path):
    log = tmp_path / "corrections.jsonl"
    fits = lambda k: {(e.a, e.b) for e in k.graph.edges if e.kind == "interfaces" and e.source == "inferred"}
    assert ("D-003", "D-023") not in fits(KnowledgeBase.load(log))
    c = corrections.propose(KnowledgeBase.load(log), "D-023.p1.vision.c06", "Ø262,0 j7 +0,026 / -0,026", "The sheet prints j7.", "", log)
    corrections.decide(c.id, True, "Reviewer", "checked the sheet", log)
    assert {("D-003", "D-023"), ("D-023", "D-003")} & fits(KnowledgeBase.load(log))
