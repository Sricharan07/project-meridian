"""The broader review loop: more kinds of correction, and measures that show what each one changed."""

import pytest

from meridian import corrections, graph, learning
from meridian.knowledge import KnowledgeBase


@pytest.fixture
def log(tmp_path):
    return tmp_path / "corrections.jsonl"


def accept(c, log, **kw):
    return corrections.decide(c.id, True, "Reviewer", "checked", log, **kw)


def test_settling_a_dispute_corrects_the_field(log):
    c = corrections.propose(KnowledgeBase.load(log), "D-011.p1.weight.ocr", "415.3", "OCR lost the decimal point.", "", log, kind="dispute")
    assert any(k["name"] == "The other reader" and k["result"] == "pass" for k in c.checks)
    accept(c, log)
    weight = KnowledgeBase.load(log).field("D-011", 1, "weight")
    assert (weight["status"], weight["value"]) == ("corrected", "415.3")


def test_a_link_change_moves_the_link_and_keeps_the_curated_one(log):
    c = corrections.propose_link(KnowledgeBase.load(log), "D-016", [81], "linked", "The opening matches.", "", log)
    assert any(k["name"] == "Automatic linker" and k["result"] == "pass" for k in c.checks)
    accept(c, log)
    kb = KnowledgeBase.load(log)
    assert kb.links["D-016"].parsed["status"] == "linked"
    assert kb.obs["D-016.bom-link"].parsed["status"] == "probable"  # the curated decision is still there


def test_a_link_to_a_row_that_does_not_exist_is_refused(log):
    with pytest.raises(ValueError, match="No BOM row 999"):
        corrections.propose_link(KnowledgeBase.load(log), "D-016", [999], "linked", "typo", "", log)


def test_a_connection_added_in_review_is_its_own_kind(log):
    c = corrections.propose_relation(KnowledgeBase.load(log), "D-015", "D-013", "is clamped by", "Hole pitch matches.", "", log=log)
    accept(c, log)
    kb = KnowledgeBase.load(log)
    assert [h["source"] for h in graph.path(kb.graph, "D-015", "D-013")["hops"]] == ["reviewed"]
    assert any(i["kind"] == "reviewed" for i in kb.interfaces("D-015"))


def test_a_withdrawn_connection_leaves_answers_but_its_evidence_stays(log):
    kb = KnowledgeBase.load(log)
    r = next(r for r in kb.relations if r.kind == "diagram")
    accept(corrections.propose_relation(kb, r.a, r.b, "", "Misread arrow.", "", remove=True, log=log), log)
    kb = KnowledgeBase.load(log)
    assert all(x.id != r.id for x in kb.relations)
    assert all(e in kb.obs for e in r.evidence)


def test_the_timeline_shows_what_each_correction_moved(log):
    accept(corrections.propose(KnowledgeBase.load(log), "D-023.p1.vision.c06", "Ø262,0 j7 +0,026 / -0,026", "j7 on the sheet.", "", log), log)
    accept(corrections.propose(KnowledgeBase.load(log), "D-011.p1.weight.ocr", "415.3", "Read the sheet.", "", log, kind="dispute"), log)
    t = learning.timeline(log)
    assert (t["before"]["scan_right"], t["before"]["scan_disputed"], t["before"]["fit_failures"]) == (58, 11, 3)
    first, second = ({c["measure"]: (c["before"], c["after"]) for c in s["changes"]} for s in t["steps"])
    assert first["fit_failures"] == (3, 2) and first["connections"] == (43, 44)
    assert second["scan_right"] == (58, 59) and second["scan_disputed"] == (11, 10)
    assert t["now"]["corrected_wrong"] == 0
