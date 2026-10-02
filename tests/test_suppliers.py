"""Supplier suggestions: only what the search actually returned, said with how strong the match is."""

import json

import pytest

from meridian import config, evidence, suppliers
from meridian.knowledge import KnowledgeBase


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase.load()


def test_a_suggestion_must_be_on_a_site_the_search_returned_and_not_the_recorded_supplier(tmp_path, monkeypatch):
    monkeypatch.setattr(suppliers, "CACHE", tmp_path)
    monkeypatch.setattr(suppliers, "SNAPSHOT", tmp_path / "suppliers.jsonl")
    observations = list(evidence.read_jsonl(config.KB / "observations.jsonl"))
    laser = next(p for p in suppliers.bought_parts(observations) if p["row"] == 84)
    alternatives = [
        ("Seller A", "https://www.seller-a.com/p/mfsc-300w", True),       # part number in the address
        ("Seller B", "https://seller-b.dk/lasers/300w", True),            # found, not confirmed
        ("Maker C", "https://maker-c.cn/fiber-laser", False),             # a different part
        ("Invented", "https://not-in-the-results.com/mfsc-300w", True),   # no search returned this site
        ("Recorded", "http://en.maxphotonics.com/product/18.html", True), # the supplier the BOM already names
    ]
    record = {"retrieved": "2026-10-02", "searches": 2, "usage": {"input_tokens": 0, "output_tokens": 0},
              "sources": ["https://seller-a.com/p/mfsc-300w?x=1", "https://www.seller-b.dk/lasers", "https://maker-c.cn/",
                          "http://en.maxphotonics.com/product/18.html"],
              "result": {"manufacturer": "Maxphotonics", "part_number": "MFSC-300W", "own_brand": False, "description": "",
                         "alternatives": [{"company": c, "url": u, "same_part": s, "note": ""} for c, u, s in alternatives]}}
    key = suppliers._key(suppliers.PART_INSTRUCTIONS, suppliers._part_query(laser), suppliers.PART_SCHEMA)
    (tmp_path / f"{key}.json").write_text(json.dumps(record))

    suppliers.snapshot(observations)
    kept = {o.value: o.parsed["match"] for o in evidence.read_jsonl(tmp_path / "suppliers.jsonl") if o.field == "suggested_supplier"}
    assert kept == {"Seller A": "part number confirmed", "Seller B": "found by the search", "Maker C": "equivalent"}
    dropped = {d["company"]: d["why"] for d in json.loads((tmp_path / "dropped.json").read_text())}
    assert dropped == {"Invented": "not a site the search returned", "Recorded": "the recorded supplier"}


def test_a_part_number_is_told_apart_from_a_sentence():
    assert suppliers._part_number("SC501MF (likely 1.5 kW model)") == ("SC501MF", "likely 1.5 kW model")
    assert suppliers._part_number("TTPA18T5200-B-P6.35") == ("TTPA18T5200-B-P6.35", "")
    assert suppliers._part_number("DN-19 GS-SRV") == ("DN-19 GS-SRV", "")
    assert suppliers._part_number("Unknown — the name does not identify a model")[0] is None
    assert suppliers._part_number("Not stated (listing says “Does not apply”)")[0] is None


def test_a_row_that_was_not_searched_says_why(kb):
    (row,) = kb.suppliers("BOM.100")["parts"]
    assert "under the DKK 200 threshold" in row["not_searched"]


def test_bought_part_suggestions_are_cited_and_dated(kb):
    (row,) = kb.suppliers("BOM.108")["parts"]
    assert row["recorded"]["supplier"]["value"] == "RS components"
    assert row["identified_as"]["retrieved"] and row["suggested"]
    assert all(kb.evidence(s["cite"])["method"] == "web" for s in row["suggested"])


def test_a_custom_part_profile_comes_from_its_cited_facts(kb):
    (plate,) = kb.suppliers("D-028")["parts"]
    need = plate["requirements"]
    assert need["materials"] == ["aluminium"]
    assert [p["process"] for p in need["processes"]] == ["sheet"]  # 2 mm thick
    assert need["size"]["mm"] == 30.0  # the bounding box, not the 19 mm between end centres
    (blade,) = kb.suppliers("D-015")["parts"]
    assert [p["process"] for p in blade["requirements"]["processes"]] == ["waterjet"]


def test_a_maker_that_lists_other_materials_is_not_suggested(kb):
    (block,) = kb.suppliers("D-012")["parts"]  # aluminium, milled
    for maker in block["makers"]:
        stated = kb.obs[maker["cite"]].parsed
        assert not stated["stated_materials"] or "aluminium" in stated["families"]
