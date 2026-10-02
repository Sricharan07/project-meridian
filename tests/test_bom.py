from functools import cache

from meridian.bom import read_bom


@cache
def cells() -> dict:
    return {o.id: o for o in read_bom()}


def test_rows_are_numbered_as_a_spreadsheet_shows_them():
    assert cells()["BOM.30.name"].value == "Recoater Arm"
    assert cells()["BOM.30.name"].source.label() == "BOM row 30 · Name"


def test_cells_are_kept_as_exported_typos_included():
    assert cells()["BOM.30.order_status"].value == "Recieved"
    assert cells()["BOM.30.design_intent"].source.column == "Design Intend"


def test_attachment_links_carry_their_expiry():
    datasheet = cells()["BOM.31.datasheet"]
    assert datasheet.parsed == {"files": ["RecoaterPlate.pdf"], "url_expired_on": ["2024-10-09"]}


def test_money_and_counts():
    assert cells()["BOM.84.unit_cost"].parsed == {"dkk": 45000.0}
    assert cells()["BOM.3.amount"].parsed == {"count": 4}


def test_link_without_scheme_is_noted_not_fixed():
    link = cells()["BOM.58.link"]
    assert link.value.startswith("dk.rs-online.com")
    assert link.parsed["scheme_missing"]


def test_material_cells_are_normalised_alongside_the_raw_list():
    assert cells()["BOM.48.material"].parsed == {"items": ["Stainless steel", "Steel"], "families": ["stainless steel", "steel"]}
