from meridian import materials


def test_library_suffix_is_ignored_on_both_alloys_it_appears_on():
    assert materials.read("7075-T6, Plate (SS)")["families"] == ["aluminium"]
    assert materials.read("AISI 316 Stainless Steel Sheet (SS)")["families"] == ["stainless steel"]


def test_werkstoff_number_and_en_name_are_the_same_alloy():
    assert materials.read("3.3315 (EN-AW 5005)")["grades"] == ["EN AW-5005"]


def test_danish_and_shorthand():
    assert materials.read("Byggeplade, rustfri og alu.")["families"] == ["stainless steel", "aluminium"]
    assert materials.read("Alu.")["families"] == ["aluminium"]


def test_stainless_steel_is_not_also_steel():
    assert materials.read("Non-magnetic stainless")["families"] == ["stainless steel"]
    assert materials.read("Stainless steel,Steel")["families"] == ["stainless steel", "steel"]


def test_a_series_is_not_a_grade():
    found = materials.read("Brug gerne EN AW-6000, AW-2000 eller AW-7000 serie aluminium.")
    assert found == {"families": ["aluminium"]}


def test_no_material_named():
    assert materials.read("M5 weld nuts on inside of flanges") is None
