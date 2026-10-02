"""What an answer may and may not say, mechanically."""

from meridian.chat.verify import check, cited_ids

TOOLS = [{"weight": "7822.5", "callout": "Ø262,0 H8 +0,081 / 0,000", "total_recorded_dkk": 5627.0, "thread": "M6-6H"}]
KNOWN = {"D-026.p1.weight", "D-003.p1.vision.c15", "BOM.10.total_cost"}


def test_figures_from_the_tools_pass_in_their_printed_form():
    answer = "The plate weighs 7822.5 g [D-026.p1.weight] and the bore is Ø262,0 H8 [D-003.p1.vision.c15]."
    assert check(answer, "", TOOLS, KNOWN).ok


def test_a_converted_figure_is_caught():
    assert check("It weighs about 7.8 kg.", "", TOOLS, KNOWN).untraced_numbers == ["7.8"]


def test_a_diameter_cannot_slip_past_because_of_the_symbol():
    assert check("The bore is Ø264,0.", "", TOOLS, KNOWN).untraced_numbers == ["264,0"]


def test_money_is_checked_with_its_thousands_separator():
    assert check("The recorded total is DKK5,627.00.", "", TOOLS, KNOWN).ok
    assert check("The recorded total is DKK5,900.00.", "", TOOLS, KNOWN).untraced_numbers == ["5900.00"]


def test_identifiers_and_small_counts_are_not_figures():
    assert check("Three drawings use M6 - 6H threads, see D-012 and EN AW-5005.", "", TOOLS, KNOWN).ok


def test_invented_citation_is_caught():
    verdict = check("Aluminium [BOM.30.colour].", "", TOOLS, KNOWN)
    assert verdict.unknown_citations == ["BOM.30.colour"]


def test_grouped_citations_are_split():
    assert cited_ids("x [D-026.p1.weight; BOM.10.total_cost] y [D-003.p1.vision.c15]") == [
        "D-026.p1.weight", "BOM.10.total_cost", "D-003.p1.vision.c15"]
