"""When a field may be called confirmed, and when it may not."""

from meridian.evidence import Method, Observation, Source
from meridian.reading import Status, settle


def reading(method: Method, value: str, confidence: float | None = None, legibility: str | None = None) -> Observation:
    return Observation(
        id=f"D-099.p1.weight.{method.value}",
        subject="D-099",
        field="weight",
        value=value,
        source=Source(doc="D-099", page=1),
        method=method,
        confidence=confidence,
        parsed={"legibility": legibility} if legibility else None,
    )


def test_vector_text_is_exact():
    assert settle([reading(Method.PDF_TEXT, "117.3")])[0] is Status.EXACT


def test_two_readers_agreeing_confirm():
    status, shown = settle([reading(Method.OCR, "107.4", 0.76), reading(Method.VISION, "107.4", 0.9, "clear")])
    assert status is Status.CONFIRMED and shown.value == "107.4"


def test_two_readers_disagreeing_show_neither():
    status, shown = settle([reading(Method.OCR, "4153", 0.81), reading(Method.VISION, "415.3", 0.9, "clear")])
    assert status is Status.DISPUTED and shown is None


def test_a_reader_that_does_not_trust_itself_abstains():
    # D-023: OCR read 3195.5 as "31985" at 0.35 confidence. That is not a second opinion.
    status, shown = settle([reading(Method.OCR, "31985", 0.35), reading(Method.VISION, "3195.5", 0.9, "clear")])
    assert status is Status.SINGLE and shown.value == "3195.5"


def test_blank_needs_someone_to_say_blank():
    assert settle([reading(Method.OCR, "")])[0] is Status.ILLEGIBLE
    assert settle([reading(Method.OCR, ""), reading(Method.VISION, "", 0.9, "blank")])[0] is Status.BLANK
