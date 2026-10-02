"""ISO 286 as a consistency check on fit readings."""

from meridian import iso286
from meridian.sheets.callouts import parse


def test_it_grades_for_sizes_on_these_sheets():
    assert iso286.it_value(262, 7) == 52
    assert iso286.it_value(262, 8) == 81
    assert iso286.it_value(8, 8) == 22
    assert iso286.it_value(22, 9) == 52


def test_every_clean_sheet_style_reading_holds_together():
    assert not iso286.problems("H8", 262, 0.081, 0.0)    # D-003 main platform bore
    assert not iso286.problems("g8", 8, -0.005, -0.027)  # D-007 dispenser shaft
    assert not iso286.problems("H6", 13, 0.011, 0.0)     # D-029


def test_the_vision_models_misread_breaks_the_h_rule_but_not_the_band():
    found = iso286.problems("H7", 262, 0.026, -0.026)  # the sheet says j7
    assert len(found) == 1 and "lower deviation of 0" in found[0]
    assert not iso286.problems("j7", 262, 0.026, -0.026)


def test_an_unprinted_zero_deviation_is_still_checked():
    # D-024: "H9 +0,052" grouped with the Ø3,3 holes; 52 µm is IT9 for Ø22, not Ø3,3.
    assert "IT9 at Ø3.3 is 30" in iso286.problems("H9", 3.3, 0.052, None)[0]


def test_fit_moves_to_the_counterbore_it_belongs_to():
    p = parse("Ø13,50 THRU / H6 +0,013 / 0,000 / ⌴ Ø20,00 ↧4,00")  # D-030, as the vision model read it
    assert "fit" not in p and "fit_check" not in p
    assert p["counterbore"]["fit"] == "H6" and p["counterbore"]["diameter"] == 20.0
