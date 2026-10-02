"""Finding a part from the words a person would use."""

from meridian.knowledge import KnowledgeBase

kb = KnowledgeBase.load()


def test_a_bought_part_is_found_by_what_its_abbreviation_stands_for():
    assert kb.find("24 V power supply")[0]["ref"] == "BOM.108"  # "24VDC PSU 20A"
    assert kb.find("temperature controller")[0]["ref"] == "BOM.117"  # "Heater PID"


def test_a_misspelt_name_still_finds_the_part():
    assert kb.find("whats the weigth of the recoter arm")[0]["ref"] == "D-011"
    assert kb.find("biuld plate")[0]["ref"] == "D-026"


def test_a_word_that_names_nothing_finds_nothing():
    assert kb.find("who could make something nobody asked about") == []


def test_a_danish_title_is_found_in_english():
    assert kb.find("cylinder clamp ring")[0]["ref"] == "D-027"  # "Cylinder Spænd Ring"
