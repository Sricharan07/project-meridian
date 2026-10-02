"""Callout text as it comes off these sheets, and what it must be read as."""

from meridian.sheets.callouts import parse


def test_hole_callout_with_thread():
    p = parse("2 x Ø5,0 THRU ALL / M6 - 6H THRU ALL")
    assert p == {"count": 2, "diameter": 5.0, "thread": "M6-6H", "thru": True, "kind": "hole"}


def test_stacked_numbers_are_a_limit_only_when_laid_out_as_one():
    # D-026 prints the build plate thickness as 25,0 over 15,0 in one tight stack.
    assert parse("25,0 / 15,0", stacked_pair=True) == {"limits": [15.0, 25.0], "kind": "limit"}
    # D-024 has 7,0 and 3,0 a full line apart: two separate dimensions.
    assert parse("7,0 / 3,0", stacked_pair=False)["values"] == [7.0, 3.0]


def test_fit_with_one_sided_tolerance():
    p = parse("H8 +0,081 / Ø264,0 0,000")
    assert p["fit"] == "H8" and p["diameter"] == 264.0
    assert p["tolerance"] == {"upper": 0.081, "lower": 0.0}


def test_counterbore_depth_belongs_to_the_counterbore():
    p = parse("3 x Ø5,3 THRU ALL / ⌴Ø10,0 ↧15,4")
    assert p["diameter"] == 5.3
    assert p["counterbore"] == {"diameter": 10.0, "depth": 15.4}


def test_depth_tolerance_is_not_the_fit_tolerance():
    # D-027: the H7 band (21 µm, IT7 at Ø20) belongs to the counterbore; ±0,05 belongs to its depth.
    p = parse("H7 +0,021 / 3 x ⌴Ø20,0 0,000 ↧4,0 ±0,05")
    assert p["counterbore"]["fit"] == "H7"
    assert p["counterbore"]["tolerance"] == {"upper": 0.021, "lower": 0.0}
    assert p["depth"] == 4.0 and p["depth_tolerance"] == 0.05


def test_thread_keeps_its_own_depth():
    assert parse("10 x Ø3,3 ↧10,1 / M4 - 6H ↧8,0")["thread"] == "M4-6H, 8 deep"


def test_slot_is_width_by_length():
    assert parse("4 x 5,5 X 10,0 THRU ALL")["slot"] == {"width": 5.5, "length": 10.0}


def test_chamfer_and_countersink_are_told_apart_by_angle():
    assert parse("3,0 X 45°")["chamfer"] == {"size": 3.0, "angle": 45.0}
    assert parse("8 x Ø3,4 THRU ALL / Ø6,9 X 90°")["countersink"] == {"size": 6.9, "angle": 90.0}


def test_prose_is_kept_as_a_remark_and_never_mined_for_numbers():
    p = parse("3 x Ø11,0 THRU ALL / Ø24,4 X 90° / Obs. Ekstra undersænkning")
    assert p["remark"] == "Obs. Ekstra undersænkning" and p["count"] == 3
    assert parse("Holds 210x297mm / laser window") == {"kind": "note", "remark": "Holds 210x297mm / laser window"}


def test_view_labels_are_not_dimensions():
    p = parse("2,0 / DETAIL B / SCALE 2 : 3")
    assert p["value"] == 2.0 and p["view"] == "DETAIL B / SCALE 2 : 3"
