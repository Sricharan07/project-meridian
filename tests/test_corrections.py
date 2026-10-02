"""A correction changes the answer only after a person accepts it, and never erases what it replaced."""

import pytest

from meridian import corrections
from meridian.knowledge import KnowledgeBase

MISREAD = "D-023.p1.vision.c06"  # the vision model read the sheet's "j7" as "H7"
FIXED = "Ø262,0 j7 +0,026 / -0,026"


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(corrections, "LOG", tmp_path / "corrections.jsonl")


def fits(kb: KnowledgeBase, drawing: str) -> list[str]:
    return [r.relation for r in kb.relations if r.kind == "inferred" and drawing in (r.a, r.b)]


def test_a_proposal_is_checked_and_changes_nothing_yet(log):
    kb = KnowledgeBase.load()
    c = corrections.propose(kb, MISREAD, FIXED, "The sheet prints j7.", "the 262 fit is j7")
    assert c.status == "pending"
    assert any(k["name"] == "ISO 286" and k["result"] == "pass" for k in c.checks)
    assert any(i["change"] == "adds" and "H8/j7 transition fit" in i["what"] for i in c.impact)
    assert fits(KnowledgeBase.load(), "D-023") == []


def test_accepting_changes_the_answer_and_keeps_the_original(log):
    c = corrections.propose(KnowledgeBase.load(), MISREAD, FIXED, "The sheet prints j7.", "")
    corrections.decide(c.id, True, "Reviewer", "checked the sheet")
    kb = KnowledgeBase.load()
    assert fits(kb, "D-023") == ["Ø262 H8/j7 transition fit"]
    original = kb.evidence(MISREAD)
    assert original["value"] == "Ø262,0 H7 +0,026 / -0,026"
    assert original["superseded_by"] == f"{MISREAD}.{c.id}"


def test_rejecting_leaves_knowledge_as_it_was(log):
    c = corrections.propose(KnowledgeBase.load(), MISREAD, FIXED, "", "")
    corrections.decide(c.id, False, "Reviewer", "not convinced")
    kb = KnowledgeBase.load()
    assert fits(kb, "D-023") == []
    assert kb.corrections_for("D-023")[0]["status"] == "rejected"


def test_a_decision_needs_a_name_and_happens_once(log):
    c = corrections.propose(KnowledgeBase.load(), MISREAD, FIXED, "", "")
    with pytest.raises(ValueError):
        corrections.decide(c.id, True, "  ", "")
    corrections.decide(c.id, True, "Reviewer", "")
    with pytest.raises(ValueError):
        corrections.decide(c.id, False, "Someone else", "")


def test_a_wrong_material_is_flagged_against_the_other_sources(log):
    c = corrections.propose(KnowledgeBase.load(), "D-026.p1.material", "Aluminium", "I think it is aluminium", "")
    assert any(k["name"] == "Other sources" and k["result"] == "fail" for k in c.checks)
