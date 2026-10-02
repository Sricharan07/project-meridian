"""Reading real clean sheets end to end."""

from functools import cache

from meridian.corpus import drawings
from meridian.sheets.vector import read_clean


@cache
def sheet(drawing_id: str) -> dict[str, object]:
    return {o.id: o for o in read_clean(drawings()[drawing_id])}


def callouts(drawing_id: str) -> list[str]:
    return [o.value for o in sheet(drawing_id).values() if o.field == "callout"]


def test_title_block_fields_are_read_by_cell():
    s = sheet("D-012")
    assert s["D-012.p1.title"].value == "Recoater Mount Block"
    assert s["D-012.p1.material"].value == "3.3315 (EN-AW 5005)"
    assert s["D-012.p1.weight"].parsed == {"grams": 117.3}
    assert s["D-012.p1.scale"].value == "1:1"


def test_empty_field_is_recorded_as_empty_not_skipped():
    # D-002 leaves MATERIAL blank and names the material in its note instead.
    s = sheet("D-002")
    assert s["D-002.p1.material"].blank
    assert s["D-002.p1.note"].parsed["materials"]["families"] == ["stainless steel"]


def test_drawn_diameter_symbol_is_restored():
    assert "2 x Ø5,0 THRU ALL / M6 - 6H THRU ALL" in callouts("D-012")
    assert "Ø250,0" in callouts("D-026")  # rotated leader text


def test_limit_dimension_on_build_plate():
    thickness = next(o for o in sheet("D-026").values() if o.field == "callout" and o.parsed.get("kind") == "limit")
    assert thickness.parsed["limits"] == [15.0, 25.0]


def test_ss_suffix_does_not_make_an_aluminium_part_stainless():
    material = sheet("D-016")["D-016.p1.material"]
    assert material.value == "7075-T6, Plate (SS)"
    assert material.parsed["families"] == ["aluminium"]


def test_template_placeholder_title_is_flagged():
    assert sheet("D-019")["D-019.p1.title"].parsed == {"placeholder": True}


def test_every_observation_points_at_a_region_of_its_sheet():
    for drawing_id in ("D-005", "D-024", "D-027"):
        for o in sheet(drawing_id).values():
            x0, y0, x1, y1 = o.source.bbox
            assert 0 <= x0 < x1 <= 1191 and 0 <= y0 < y1 <= 842, o.id
