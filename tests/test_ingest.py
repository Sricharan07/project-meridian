"""A drawing added in the app is read by the build's own readers, and joins only when a person accepts it."""

import pytest

from meridian import config, corrections, ingest
from meridian.evidence import Method
from meridian.knowledge import KnowledgeBase


@pytest.fixture
def var(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "DIR", tmp_path / "ingest")
    return tmp_path / "corrections.jsonl"


def readings(observations, subject):
    return {(o.field, o.source.page, o.value) for o in observations if o.subject == subject and o.method == Method.PDF_TEXT}


def test_an_added_drawing_is_read_exactly_as_the_build_read_it(var, monkeypatch):
    built = readings(KnowledgeBase.load(var).base_observations, "D-028")
    monkeypatch.setattr(ingest, "HOLD_OUT", {"D-028"})
    kb = KnowledgeBase.load(var)
    assert "D-028" not in kb.sheets

    c = ingest.add(kb, (config.DRAWINGS / "D-028.pdf").read_bytes(), "D-028.pdf", "Z-axis", "held out to test the upload path", log=var)
    assert c.kind == "drawing" and c.status == "pending"
    assert c.subject not in KnowledgeBase.load(var).sheets  # nothing joins before review
    assert c.payload["candidates"][0]["row"] == 51            # the linker finds the heating element row

    corrections.decide(c.id, True, "Reviewer", "matches row 51", var, link={"rows": [51], "status": "linked"})
    kb = KnowledgeBase.load(var)
    added = {(field, page, value) for field, page, value in readings(kb.base_observations, c.subject)}
    assert added == built
    assert kb.links[c.subject].parsed["rows"] == [51]
    assert c.subject in kb.graph.nodes


def test_a_supplied_drawing_cannot_be_added_again(var):
    with pytest.raises(ValueError, match="already in the knowledge base as D-028"):
        ingest.add(KnowledgeBase.load(var), (config.DRAWINGS / "D-028.pdf").read_bytes(), "copy.pdf", "Z-axis", "a copy", log=var)


def test_something_that_is_not_a_pdf_is_refused(var):
    with pytest.raises(ValueError, match="not a PDF"):
        ingest.add(KnowledgeBase.load(var), b"hello", "notes.txt", "Box", "a test", log=var)
